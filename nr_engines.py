"""实时降噪引擎：TorchGate / RNNoise / DTLN，支持链式串联。

统一接口：``__call__(x)`` 收 mono float32 torch 张量（任意长），返回同长降噪结果。
RNNoise / DTLN 是有状态引擎，内部跨块维护帧缓冲与模型状态；
TorchGate 包装 RVC 自带的 tools.torchgate，输入侧沿用原 nr_buffer crossfade 逻辑，
输出侧维护 output_buffer 参考（与原 realtime_gui.py 逐字等价）。
"""

import os

import numpy as np
import torch
import librosa

from pyrnnoise.rnnoise import (
    FRAME_SIZE,
    SAMPLE_RATE as RN_SR,
    create,
    destroy,
    process_frame,
)

import onnxruntime as ort

# DTLN onnx 模型目录（static/nr/，随分发自带）
NR_MODEL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "nr")


class TorchGateNR:
    """包装 RVC 的 TorchGate（频谱门控）。"""

    def __init__(self, tg, block_frame, sola_frame, fade_in, fade_out, ref, device, out_mode=False):
        self.tg = tg
        self.block_frame = block_frame
        self.sola = sola_frame
        self.fade_in = fade_in
        self.fade_out = fade_out
        self.ref = ref  # 输入侧=整个 input_wav；输出侧=output_buffer
        self.device = device
        self.out_mode = out_mode
        self.nr_buffer = torch.zeros(sola_frame, device=device, dtype=torch.float32)

    def __call__(self, x):
        if self.out_mode:
            # 输出侧：原 output_buffer 前移 + 塞尾部作为参考
            self.ref[:-self.block_frame] = self.ref[self.block_frame:].clone()
            self.ref[-self.block_frame:] = x[-self.block_frame:]
            return self.tg(x.unsqueeze(0), self.ref.unsqueeze(0)).squeeze(0)
        # 输入侧：nr_buffer 历史 + 当前块 crossfade 防接缝
        n = x.shape[0]
        ctx = torch.cat([self.nr_buffer, x])
        y = self.tg(ctx.unsqueeze(0), self.ref.unsqueeze(0)).squeeze(0)
        y[:self.sola] = y[:self.sola] * self.fade_in + self.nr_buffer * self.fade_out
        self.nr_buffer[:] = y[n:]
        return y[:n]


class RNNoiseDenoiser:
    """pyrnnoise 原版 RNNoise（48kHz / 480 采样 / 10ms 帧）。"""

    def __init__(self, sr, device):
        self.sr = int(sr)
        self.device = device
        self.state = create()
        self.buf48 = np.zeros(0, dtype=np.float32)

    def close(self):
        if self.state is not None:
            destroy(self.state)
            self.state = None

    def __del__(self):
        self.close()

    def __call__(self, x):
        n = x.shape[0]
        if n == 0 or self.state is None:
            return x
        y = x.cpu().numpy().astype(np.float32)
        if self.sr != RN_SR:
            y = librosa.resample(y, orig_sr=self.sr, target_sr=RN_SR)
        self.buf48 = np.concatenate([self.buf48, y])
        nf = len(self.buf48) // FRAME_SIZE
        if nf:
            frames = np.ascontiguousarray(self.buf48[:nf * FRAME_SIZE]).reshape(nf, FRAME_SIZE)
            out = np.empty(nf * FRAME_SIZE, dtype=np.float32)
            for i in range(nf):
                # pyrnnoise 要求输入在 [-1,1]（或 int16）；重采样可能轻微过冲，clip 兜底
                f = np.clip(frames[i], -1.0, 1.0)
                d, _ = process_frame(self.state, f)
                out[i * FRAME_SIZE:(i + 1) * FRAME_SIZE] = d.astype(np.float32) / 32767.0
            self.buf48 = self.buf48[nf * FRAME_SIZE:]
        else:
            out = np.zeros(0, dtype=np.float32)
        if self.sr != RN_SR:
            out = librosa.resample(out, orig_sr=RN_SR, target_sr=self.sr) if out.size else np.zeros(0)
        if out.size < n:
            out = np.pad(out, (0, n - out.size))
        else:
            out = out[:n]
        return torch.from_numpy(out).to(self.device)


class DTLNDenoiser:
    """breizhn/DTLN 双 stage LSTM 降噪（16kHz，块 512 / 跳 128），onnxruntime 流式。

    流程对齐官方 real_time_processing_onnx.py：512 窗口 rfft → model_1 出掩码乘幅值 →
    结合相位 irfft → model_2 时域增强 → OLA 输出尾部 hop。
    """

    FRAME = 512
    HOP = 128

    def __init__(self, model_dir, sr, device):
        self.sr = int(sr)
        self.device = device
        self.sess1 = ort.InferenceSession(
            os.path.join(model_dir, "model_1.onnx"), providers=["CPUExecutionProvider"]
        )
        self.sess2 = ort.InferenceSession(
            os.path.join(model_dir, "model_2.onnx"), providers=["CPUExecutionProvider"]
        )
        # 预分配模型输入（state 就地保持，跨块延续）
        self.in1 = {
            i.name: np.zeros([d if isinstance(d, int) else 1 for d in i.shape], np.float32)
            for i in self.sess1.get_inputs()
        }
        self.in2 = {
            i.name: np.zeros([d if isinstance(d, int) else 1 for d in i.shape], np.float32)
            for i in self.sess2.get_inputs()
        }
        self.names1 = [i.name for i in self.sess1.get_inputs()]
        self.names2 = [i.name for i in self.sess2.get_inputs()]
        self.in_buf = np.zeros(self.FRAME, dtype=np.float32)  # 16k 域滑窗
        self.out_buf = np.zeros(self.FRAME, dtype=np.float32)  # OLA 累积

    def close(self):
        self.sess1 = None
        self.sess2 = None

    def __call__(self, x):
        n = x.shape[0]
        if n == 0 or self.sess1 is None:
            return x
        y = x.cpu().numpy().astype(np.float32)
        if self.sr != 16000:
            y = librosa.resample(y, orig_sr=self.sr, target_sr=16000)
        out = np.zeros(0, dtype=np.float32)
        pos = 0
        while pos < y.shape[0]:
            take = min(self.HOP, y.shape[0] - pos)
            self.in_buf[:-take] = self.in_buf[take:]
            self.in_buf[-take:] = y[pos:pos + take]
            fft = np.fft.rfft(self.in_buf)
            mag = np.abs(fft).reshape(1, 1, -1).astype(np.float32)
            phase = np.angle(fft)
            self.in1[self.names1[0]] = mag
            o1 = self.sess1.run(None, self.in1)
            self.in1[self.names1[1]] = o1[1]
            est = mag * o1[0] * np.exp(1j * phase)
            est_block = np.fft.irfft(est).reshape(1, 1, -1).astype(np.float32)
            self.in2[self.names2[0]] = est_block
            o2 = self.sess2.run(None, self.in2)
            self.in2[self.names2[1]] = o2[1]
            self.out_buf[:-take] = self.out_buf[take:]
            self.out_buf[-take:] = 0.0
            self.out_buf += np.squeeze(o2[0])
            out = np.concatenate([out, self.out_buf[:take]])
            pos += take
        if self.sr != 16000:
            out = librosa.resample(out, orig_sr=16000, target_sr=self.sr) if out.size else np.zeros(0)
        if out.size < n:
            out = np.pad(out, (0, n - out.size))
        else:
            out = out[:n]
        return torch.from_numpy(out).to(self.device)


class NRChain:
    """降噪链：按顺序串联多个引擎，上级输出喂给下级。

    chain 元素可为算法字符串（构建内置引擎）或插件 dict（经 vst_builder 注入构建，
    保持链内混排顺序）；vst_builder 返回 None 表示该元素被跳过。
    """

    def __init__(self, chain, sr, tg, block_frame, sola_frame, fade_in, fade_out, ref, device, out_mode=False, vst_builder=None):
        self.engines = []
        for el in chain:
            if isinstance(el, str):
                if el == "TorchGate":
                    self.engines.append(
                        TorchGateNR(tg, block_frame, sola_frame, fade_in, fade_out, ref, device, out_mode)
                    )
                elif el == "RNNoise":
                    self.engines.append(RNNoiseDenoiser(sr, device))
                elif el == "DTLN":
                    self.engines.append(DTLNDenoiser(NR_MODEL_DIR, sr, device))
            elif isinstance(el, dict) and vst_builder is not None:
                eng = vst_builder(el)
                if eng is not None:
                    self.engines.append(eng)

    def __call__(self, x):
        for eng in self.engines:
            x = eng(x)
        return x

    def close(self):
        for eng in self.engines:
            if hasattr(eng, "close"):
                eng.close()
        self.engines = []
