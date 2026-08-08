import os
import sys
import threading
import time
import traceback

import librosa
import numpy as np
import sounddevice as sd
import torch
import torch.nn.functional as F
import torchaudio.transforms as tat

from tools.torchgate import TorchGate
from infer import rtrvc as rvc_for_realtime
from tools.cuda_graph import cuda_graph_enabled, run_cuda_graph

from nr_engines import NRChain

flag_vc = False


def printt(strr, *args):
    if len(args) == 0:
        print(strr)
    else:
        print(strr % args)


class AudioEngine:
    """实时变声 DSP 核心。

    代码逐字搬移自原 realtime_gui.py 的 GUI 类（start_vc / audio_callback 等），
    与 UI 框架无关。self.gui_config 是外部传入的参数对象（原 GUIConfig 字段），
    保证 DSP 内部引用逐字可用；self.config 是 RVC 的 configs.config.Config。
    """

    def __init__(self, params, config):
        self.gui_config = params  # 原 GUIConfig 字段
        self.config = config
        self.function = "vc"
        self.delay_time = 0
        self.stream = None
        self.on_status = None  # 回调 on_status(name, value)，UI 侧挂接做线程安全更新
        self._in_nr = None
        self._out_nr = None
        self._nr_lock = threading.Lock()
        self._nr_building = False
        self._nr_pending = False
        # 退休链延迟销毁：音频回调可能仍在 in-flight 旧链（含 VST 引擎 C++ 实例），
        # 立即析构会 use-after-free 崩溃；3 秒后统一 close
        self._retired_chains = []

    # ------------------------------------------------------------------
    # UI 状态回传
    # ------------------------------------------------------------------
    def _emit(self, name, value):
        if self.on_status is not None:
            self.on_status(name, value)

    # ------------------------------------------------------------------
    # 模型构建与热切换
    # ------------------------------------------------------------------
    def _build_rvc(self):
        torch.cuda.empty_cache()
        self.rvc = rvc_for_realtime.RVC(
            self.gui_config.pitch,
            self.gui_config.formant,
            self.gui_config.pth_path,
            self.gui_config.index_path,
            self.gui_config.index_rate,
            self.config,
            self.rvc if hasattr(self, "rvc") else None,
        )

    def switch_model(self, pth_path, index_path):
        """热切换模型：替换 pth/index，若正在运行则重建并恢复流。"""
        self.gui_config.pth_path = pth_path
        self.gui_config.index_path = index_path
        was_running = flag_vc
        self.stop_stream()
        if was_running:
            self.start_vc()  # start_vc 内部会以新路径 _build_rvc

    # ------------------------------------------------------------------
    # 启动 / 停止
    # ------------------------------------------------------------------
    def start_vc(self):
        self._build_rvc()
        self.gui_config.samplerate = (
            self.rvc.tgt_sr
            if self.gui_config.sr_type == "sr_model"
            else self.get_device_samplerate()
        )
        self.gui_config.channels = self.get_device_channels()
        self.zc = self.gui_config.samplerate // 100
        self.block_frame = (
            int(
                np.round(
                    self.gui_config.block_time
                    * self.gui_config.samplerate
                    / self.zc
                )
            )
            * self.zc
        )
        self.block_frame_16k = 160 * self.block_frame // self.zc
        self.crossfade_frame = (
            int(
                np.round(
                    self.gui_config.crossfade_time
                    * self.gui_config.samplerate
                    / self.zc
                )
            )
            * self.zc
        )
        self.sola_buffer_frame = min(self.crossfade_frame, 4 * self.zc)
        self.sola_search_frame = self.zc
        self.extra_frame = (
            int(
                np.round(
                    self.gui_config.extra_time
                    * self.gui_config.samplerate
                    / self.zc
                )
            )
            * self.zc
        )
        self.input_wav = torch.zeros(
            self.extra_frame
            + self.crossfade_frame
            + self.sola_search_frame
            + self.block_frame,
            device=self.config.device,
            dtype=torch.float32,
        )
        self.input_wav_denoise = self.input_wav.clone()
        self.input_wav_res = torch.zeros(
            160 * self.input_wav.shape[0] // self.zc,
            device=self.config.device,
            dtype=torch.float32,
        )
        self.rms_buffer = np.zeros(4 * self.zc, dtype="float32")
        self.sola_buffer = torch.zeros(
            self.sola_buffer_frame, device=self.config.device, dtype=torch.float32
        )
        self.sola_den_kernel = torch.ones(
            1,
            1,
            self.sola_buffer_frame,
            device=self.config.device,
            dtype=torch.float32,
        )
        self.nr_buffer = self.sola_buffer.clone()
        self.output_buffer = self.input_wav.clone()
        self.skip_head = self.extra_frame // self.zc
        self.return_length = (
            self.block_frame + self.sola_buffer_frame + self.sola_search_frame
        ) // self.zc
        self.fade_in_window = (
            torch.sin(
                0.5
                * np.pi
                * torch.linspace(
                    0.0,
                    1.0,
                    steps=self.sola_buffer_frame,
                    device=self.config.device,
                    dtype=torch.float32,
                )
            )
            ** 2
        )
        self.fade_out_window = 1 - self.fade_in_window
        self.resampler = tat.Resample(
            orig_freq=self.gui_config.samplerate,
            new_freq=16000,
            dtype=torch.float32,
        ).to(self.config.device)
        if self.rvc.tgt_sr != self.gui_config.samplerate:
            self.resampler2 = tat.Resample(
                orig_freq=self.rvc.tgt_sr,
                new_freq=self.gui_config.samplerate,
                dtype=torch.float32,
            ).to(self.config.device)
        else:
            self.resampler2 = None
        # Bundled torch.istft is not CUDA Graph-capturable, so TorchGate
        # stays eager while resampling and RVC inference still use graphs.
        self.tg = TorchGate(
            sr=self.gui_config.samplerate, n_fft=4 * self.zc, prop_decrease=0.9
        ).to(self.config.device)
        self._build_nr_chains()
        self.prewarm_cuda_graph()
        self.start_stream()
        self._emit("samplerate", self.gui_config.samplerate)
        self._emit("running", True)

    def prewarm_cuda_graph(self):
        if not cuda_graph_enabled(self.config.device):
            return
        try:
            printt("正在预热CUDA Graph")
            samples = self.input_wav_res.shape[0]
            phase = torch.arange(
                samples, device=self.config.device, dtype=torch.float32
            )
            probe = 0.05 * torch.sin(2 * np.pi * 220.0 * phase / 16000.0)
            self.input_wav_res.copy_(probe)

            if self.gui_config.I_noise_reduce and any(
                el.get("type") == "algo" and el.get("name") == "TorchGate"
                and el.get("enabled", True)
                for el in (self.gui_config.I_chain or [])
            ):
                short = self.input_wav[
                    -self.sola_buffer_frame - self.block_frame :
                ].unsqueeze(0)
                self.tg(short, self.input_wav.unsqueeze(0))

            resample_input = self.input_wav[-self.block_frame - 2 * self.zc :]
            run_cuda_graph(
                self.resampler,
                "realtime-input-resample",
                lambda audio: self.resampler(audio),
                resample_input,
            )

            inferred = self.rvc.infer(
                self.input_wav_res,
                self.block_frame_16k,
                self.skip_head,
                self.return_length,
                self.gui_config.f0method,
            )
            if self.resampler2 is not None:
                inferred = run_cuda_graph(
                    self.resampler2,
                    "realtime-output-resample",
                    lambda audio: self.resampler2(audio),
                    inferred,
                )
            if self.gui_config.O_noise_reduce:
                self.tg(inferred.unsqueeze(0), self.output_buffer.unsqueeze(0))
            torch.cuda.synchronize(self.config.device)
            printt("CUDA Graph预热完成")
        except Exception:
            printt(traceback.format_exc())
        finally:
            self.input_wav.zero_()
            self.input_wav_denoise.zero_()
            self.input_wav_res.zero_()
            self.output_buffer.zero_()
            self.sola_buffer.zero_()
            self.nr_buffer.zero_()
            self.rvc.cache_pitch.zero_()
            self.rvc.cache_pitchf.zero_()

    def start_stream(self):
        global flag_vc
        if not flag_vc:
            flag_vc = True
            if (
                "WASAPI" in self.gui_config.sg_hostapi
                and self.gui_config.sg_wasapi_exclusive
            ):
                extra_settings = sd.WasapiSettings(exclusive=True)
            else:
                extra_settings = None
            self.stream = sd.Stream(
                callback=self.audio_callback,
                blocksize=self.block_frame,
                samplerate=self.gui_config.samplerate,
                channels=self.gui_config.channels,
                dtype="float32",
                extra_settings=extra_settings,
            )
            self.stream.start()

    def stop_stream(self):
        global flag_vc
        if flag_vc:
            flag_vc = False
            if self.stream is not None:
                self.stream.abort()
                self.stream.close()
                self.stream = None
            self._emit("running", False)
        # 不在停止时销毁降噪链：重启/停流期间的 in-flight 回调仍可能访问，
        # 销毁放到下次 _build_nr_chains 重建时统一处理

    def _make_chain(self, chain, out_mode):
        enabled = [el for el in (chain or []) if el.get("enabled", True)]
        return NRChain(
            enabled,
            self.gui_config.samplerate,
            tg=self.tg,
            block_frame=self.block_frame,
            sola_frame=self.sola_buffer_frame,
            fade_in=self.fade_in_window,
            fade_out=self.fade_out_window,
            ref=self.output_buffer if out_mode else self.input_wav,
            device=self.config.device,
            out_mode=out_mode,
            vst_builder=lambda el: self._build_vst(el, out_mode),
        )

    def _build_vst(self, el, out_mode):
        """构建 VST 引擎；失败通知并返回 None（该元素直通跳过，链其余继续）。"""
        path = el.get("path", "") if isinstance(el, dict) else ""
        if not path:
            return None
        try:
            from vst_engine import VSTEngine, vst_loader
            return vst_loader.call(
                lambda: VSTEngine(path, self.gui_config.samplerate, self.config.device)
            )
        except Exception as e:
            print(f"[vst_error] load failed: {path} -> {e}", file=sys.stderr)
            traceback.print_exc()
            self._emit("vst_error", ("O" if out_mode else "I", path, str(e)))
            return None

    def _build_nr_chains(self):
        """按配置构建输入/输出降噪链（重建前先释放旧链）。"""
        self._close_nr_chains()
        if self.gui_config.I_chain:
            self._in_nr = self._make_chain(self.gui_config.I_chain, False)
        if self.gui_config.O_chain:
            self._out_nr = self._make_chain(self.gui_config.O_chain, True)
        # 预热 DTLN（onnxruntime 首次推理开销大，避免第一个音频块卡顿）
        self._warmup_nr()

    def hot_update_nr(self):
        """热切换降噪链：后台构建新链并原子替换，不重启流。

        仅运行中生效；未运行时由 start_vc 按配置构建。
        """
        if not flag_vc or self.stream is None:
            return
        with self._nr_lock:
            if self._nr_building:
                self._nr_pending = True
                return
            self._nr_building = True
        threading.Thread(target=self._build_nr_async, daemon=True).start()

    def _build_nr_async(self):
        try:
            while True:
                self._do_build_nr()
                with self._nr_lock:
                    if self._nr_pending:
                        self._nr_pending = False
                        continue
                    self._nr_building = False
                    return
        except Exception:
            traceback.print_exc()
            with self._nr_lock:
                self._nr_building = False
                self._nr_pending = False

    def _do_build_nr(self):
        """读当前配置构建新链并原子替换；旧链进退休区延迟销毁（防回调 in-flight 竞态）。"""
        in_chain = list(self.gui_config.I_chain or [])
        out_chain = list(self.gui_config.O_chain or [])
        new_in = self._make_chain(in_chain, False) if in_chain else None
        new_out = self._make_chain(out_chain, True) if out_chain else None
        block = torch.zeros(self.block_frame, device=self.config.device, dtype=torch.float32)
        for nr in (new_in, new_out):
            if nr is not None:
                nr(block)  # 预热 DTLN 首次推理
        old_in, old_out = self._in_nr, self._out_nr
        self._in_nr = new_in
        self._out_nr = new_out
        if old_in is not None or old_out is not None:
            self._retired_chains.append((old_in, old_out, time.time()))
        self._sweep_retired()

    def _sweep_retired(self):
        """销毁到期（>3s）的退休链；回调单块处理远小于 3 秒，可安全 close。"""
        now = time.time()
        keep = []
        for old_in, old_out, t in self._retired_chains:
            if now - t >= 3.0:
                for nr in (old_in, old_out):
                    if nr is not None:
                        try:
                            nr.close()
                        except Exception:
                            traceback.print_exc()
            else:
                keep.append((old_in, old_out, t))
        self._retired_chains = keep

    def _warmup_nr(self):
        block = torch.zeros(self.block_frame, device=self.config.device, dtype=torch.float32)
        for nr in (getattr(self, "_in_nr", None), getattr(self, "_out_nr", None)):
            if nr is not None:
                try:
                    nr(block)
                except Exception:
                    traceback.print_exc()

    def _close_nr_chains(self):
        # 当前链 + 退休区全部 close（停止/重启时 in-flight 回调已停，可安全销毁）
        for nr in (getattr(self, "_in_nr", None), getattr(self, "_out_nr", None)):
            if nr is not None:
                nr.close()
        self._in_nr = None
        self._out_nr = None
        for old_in, old_out, _t in self._retired_chains:
            for nr in (old_in, old_out):
                if nr is not None:
                    try:
                        nr.close()
                    except Exception:
                        traceback.print_exc()
        self._retired_chains = []

    # ------------------------------------------------------------------
    # 实时音频处理（逐字搬移）
    # ------------------------------------------------------------------
    def audio_callback(
        self, indata, outdata, frames, times, status
    ):
        """
        音频处理
        """
        global flag_vc
        start_time = time.perf_counter()
        indata = librosa.to_mono(indata.T)
        if self.gui_config.threhold > -60:
            indata = np.append(self.rms_buffer, indata)
            rms = librosa.feature.rms(
                y=indata, frame_length=4 * self.zc, hop_length=self.zc
            )[:, 2:]
            self.rms_buffer[:] = indata[-4 * self.zc :]
            indata = indata[2 * self.zc - self.zc // 2 :]
            db_threhold = (
                librosa.amplitude_to_db(rms, ref=1.0)[0] < self.gui_config.threhold
            )
            for i in range(db_threhold.shape[0]):
                if db_threhold[i]:
                    indata[i * self.zc : (i + 1) * self.zc] = 0
            indata = indata[self.zc // 2 :]
        self.input_wav[: -self.block_frame] = self.input_wav[
            self.block_frame :
        ].clone()
        self.input_wav[-indata.shape[0] :] = torch.from_numpy(indata).to(
            self.config.device
        )
        self.input_wav_res[: -self.block_frame_16k] = self.input_wav_res[
            self.block_frame_16k :
        ].clone()
        # input noise reduction and resampling
        if self.gui_config.I_noise_reduce and self.gui_config.I_chain:
            self.input_wav_denoise[: -self.block_frame] = self.input_wav_denoise[
                self.block_frame :
            ].clone()
            block = self.input_wav[-self.block_frame :]
            denoised = self._in_nr(block) if self._in_nr is not None else block
            self.input_wav_denoise[-self.block_frame :] = denoised
        else:
            # 无降噪（未开或链为空）：直通，同样维护 input_wav_denoise，
            # 保证重采样路径与链分支完全一致，切换时 input_wav_res 不错位
            self.input_wav_denoise[: -self.block_frame] = self.input_wav_denoise[
                self.block_frame :
            ].clone()
            self.input_wav_denoise[-self.block_frame :] = self.input_wav[
                -self.block_frame :
            ]
        resample_input = self.input_wav_denoise[-self.block_frame - 2 * self.zc :]
        self.input_wav_res[-self.block_frame_16k - 160 :] = run_cuda_graph(
            self.resampler,
            "realtime-input-resample",
            lambda audio: self.resampler(audio),
            resample_input,
        )[160:]
        # infer
        if self.function == "vc":
            infer_wav = self.rvc.infer(
                self.input_wav_res,
                self.block_frame_16k,
                self.skip_head,
                self.return_length,
                self.gui_config.f0method,
            )
            if self.resampler2 is not None:
                infer_wav = run_cuda_graph(
                    self.resampler2,
                    "realtime-output-resample",
                    lambda audio: self.resampler2(audio),
                    infer_wav,
                )
        elif self.gui_config.I_noise_reduce:
            infer_wav = self.input_wav_denoise[self.extra_frame :].clone()
        else:
            infer_wav = self.input_wav[self.extra_frame :].clone()
        # output noise reduction
        if (
            self.gui_config.O_noise_reduce
            and self.gui_config.O_chain
            and self.function == "vc"
        ):
            infer_wav = self._out_nr(infer_wav) if self._out_nr is not None else infer_wav
        # volume envelop mixing
        if self.gui_config.rms_mix_rate < 1 and self.function == "vc":
            if self.gui_config.I_noise_reduce:
                input_wav = self.input_wav_denoise[self.extra_frame :]
            else:
                input_wav = self.input_wav[self.extra_frame :]
            rms1 = librosa.feature.rms(
                y=input_wav[: infer_wav.shape[0]].cpu().numpy(),
                frame_length=4 * self.zc,
                hop_length=self.zc,
            )
            rms1 = torch.from_numpy(rms1).to(self.config.device)
            rms1 = F.interpolate(
                rms1.unsqueeze(0),
                size=infer_wav.shape[0] + 1,
                mode="linear",
                align_corners=True,
            )[0, 0, :-1]
            rms2 = librosa.feature.rms(
                y=infer_wav[:].cpu().numpy(),
                frame_length=4 * self.zc,
                hop_length=self.zc,
            )
            rms2 = torch.from_numpy(rms2).to(self.config.device)
            rms2 = F.interpolate(
                rms2.unsqueeze(0),
                size=infer_wav.shape[0] + 1,
                mode="linear",
                align_corners=True,
            )[0, 0, :-1]
            rms2 = torch.max(rms2, torch.zeros_like(rms2) + 1e-3)
            infer_wav *= torch.pow(
                rms1 / rms2, 1.0 - self.gui_config.rms_mix_rate
            )

        # ==================== 修正后的 SOLA 无缝拼接 ====================
        # 计算互相关，寻找最佳重叠偏移
        conv_input = infer_wav[
            None, None, : self.sola_buffer_frame + self.sola_search_frame
        ]
        cor_nom = F.conv1d(conv_input, self.sola_buffer[None, None, :])
        cor_den = torch.sqrt(
            F.conv1d(
                conv_input**2,
                self.sola_den_kernel,
            )
            + 1e-8
        )
        if sys.platform == "darwin":
            _, sola_offset = torch.max(cor_nom[0, 0] / cor_den[0, 0])
            sola_offset = sola_offset.item()
        else:
            sola_offset = torch.argmax(cor_nom[0, 0] / cor_den[0, 0])
        printt("SOLA偏移：%d", int(sola_offset))

        # 1. 在偏移处执行重叠相加（不裁切波形）
        overlap_end = sola_offset + self.sola_buffer_frame
        if overlap_end <= infer_wav.shape[0]:
            infer_wav[sola_offset:overlap_end] = (
                infer_wav[sola_offset:overlap_end] * self.fade_in_window
                + self.sola_buffer * self.fade_out_window
            )
        else:
            # 边界保护（极少发生，但保留以防万一）
            available = infer_wav.shape[0] - sola_offset
            if available > 0:
                infer_wav[sola_offset:] = (
                    infer_wav[sola_offset:] * self.fade_in_window[:available]
                    + self.sola_buffer[:available] * self.fade_out_window[:available]
                )

        # 2. 从偏移处提取输出块（若不足 block_frame 则补零）
        out_block = infer_wav[sola_offset: sola_offset + self.block_frame]
        if out_block.shape[0] < self.block_frame:
            out_block = F.pad(out_block, (0, self.block_frame - out_block.shape[0]))

        # 3. 更新 SOLA 缓冲区（取输出块之后的 buffer 长度，若不足则补零）
        buf_start = sola_offset + self.block_frame
        buf_end = buf_start + self.sola_buffer_frame
        if buf_end <= infer_wav.shape[0]:
            self.sola_buffer[:] = infer_wav[buf_start:buf_end]
        else:
            available = infer_wav.shape[0] - buf_start
            if available > 0:
                self.sola_buffer[:available] = infer_wav[buf_start:]
                self.sola_buffer[available:] = 0
            else:
                self.sola_buffer.zero_()

        # 4. 最终输出到设备
        outdata[:] = out_block.repeat(self.gui_config.channels, 1).t().cpu().numpy()
        # ==================== SOLA 修正结束 ====================

        total_time = time.perf_counter() - start_time
        if flag_vc:
            self._emit("infer_time", int(total_time * 1000))
        printt("推理耗时：%.2f秒", total_time)

    # ------------------------------------------------------------------
    # 音频设备
    # ------------------------------------------------------------------
    def update_devices(self, hostapi_name=None):
        """获取设备列表"""
        global flag_vc
        flag_vc = False
        sd._terminate()
        sd._initialize()
        devices = sd.query_devices()
        hostapis = sd.query_hostapis()
        for hostapi in hostapis:
            for device_idx in hostapi["devices"]:
                devices[device_idx]["hostapi_name"] = hostapi["name"]
        self.hostapis = [hostapi["name"] for hostapi in hostapis]
        if hostapi_name not in self.hostapis:
            hostapi_name = self.hostapis[0]
        self.input_devices = [
            d["name"]
            for d in devices
            if d["max_input_channels"] > 0 and d["hostapi_name"] == hostapi_name
        ]
        self.output_devices = [
            d["name"]
            for d in devices
            if d["max_output_channels"] > 0 and d["hostapi_name"] == hostapi_name
        ]
        self.input_devices_indices = [
            d["index"] if "index" in d else d["name"]
            for d in devices
            if d["max_input_channels"] > 0 and d["hostapi_name"] == hostapi_name
        ]
        self.output_devices_indices = [
            d["index"] if "index" in d else d["name"]
            for d in devices
            if d["max_output_channels"] > 0 and d["hostapi_name"] == hostapi_name
        ]

    def set_devices(self, input_device, output_device):
        """设置输出设备"""
        sd.default.device[0] = self.input_devices_indices[
            self.input_devices.index(input_device)
        ]
        sd.default.device[1] = self.output_devices_indices[
            self.output_devices.index(output_device)
        ]
        printt("输入设备：%s:%s", str(sd.default.device[0]), input_device)
        printt("输出设备：%s:%s", str(sd.default.device[1]), output_device)

    def get_device_samplerate(self):
        return int(
            sd.query_devices(device=sd.default.device[0])["default_samplerate"]
        )

    def get_device_channels(self):
        max_input_channels = sd.query_devices(device=sd.default.device[0])[
            "max_input_channels"
        ]
        max_output_channels = sd.query_devices(device=sd.default.device[1])[
            "max_output_channels"
        ]
        return min(max_input_channels, max_output_channels, 2)