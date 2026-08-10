# xiaoe_rvc_ui 部署安装器
# 读取上次安装路径 -> 询问更新或选择 RVC 根目录 -> 校验 -> robocopy 部署（保留用户数据）-> 快捷方式/启动
# 不写日志文件，进度与错误直接显示在控制台。
Add-Type -AssemblyName System.Windows.Forms

function Get-FolderPath {
    param([string]$Title, [string]$InitialPath)
    $dlg = New-Object System.Windows.Forms.FolderBrowserDialog
    $dlg.Description = $Title
    if ($InitialPath -and (Test-Path $InitialPath)) {
        $dlg.SelectedPath = $InitialPath
    }
    if ($dlg.ShowDialog() -ne [System.Windows.Forms.DialogResult]::OK) {
        return $null
    }
    return $dlg.SelectedPath.TrimEnd("\")
}

function Show($msg) { Write-Output $msg }

try {
    Show "============================================"
    Show "   xiaoe_rvc_ui 部署安装器"
    Show "============================================"

$Source = $PSScriptRoot

# ── 1. 校验安装包完整 ──
Show ""
Show "[1/8] 校验安装包…"
if (-not (Test-Path (Join-Path $Source "main.py")) -or -not (Test-Path (Join-Path $Source "run.vbs"))) {
    Show "✘ 安装包不完整（缺少 main.py 或 run.vbs）"
    exit 1
}
Show "✔ 安装包完整"

# ── 2. 读取上次安装路径 ──
Show ""
Show "[2/8] 选择 RVC 根目录…"
$target = $null
$last = [Environment]::GetEnvironmentVariable("XIAOE_RVC_UI_ROOT", "User")
if ($last -and (Test-Path $last)) {
    Show "检测到上次安装路径：$last，询问是否更新…"
    $r = [System.Windows.Forms.MessageBox]::Show(
        "检测到上次安装路径：`n$last`n`n是否继续安装到该路径？`n（选「否」将重新选择文件夹）",
        "xiaoe_rvc_ui 安装器", [System.Windows.Forms.MessageBoxButtons]::YesNo,
        [System.Windows.Forms.MessageBoxIcon]::Question)
    if ($r -eq [System.Windows.Forms.DialogResult]::Yes) {
        $target = $last
    }
}

# ── 3. 选择文件夹 + 4. 校验 RVC 根目录（仅检查 runtime\python.exe）──
while (-not $target) {
    $parent = Split-Path $Source -Parent
    if (Test-Path (Join-Path $parent "runtime\python.exe")) {
        $initial = $parent
    } else {
        $initial = [Environment]::GetFolderPath("Desktop")
    }
    if (-not $target) {
        Show "请在弹出的窗口中选择 RVC 解压根目录…"
    }
    $target = Get-FolderPath "请选择 RVC 根目录（解压 RVC 整合包得到的那个文件夹）" $initial
    if (-not $target) {
        exit 1  # 用户取消
    }
    Show "[3/8] 校验 RVC 根目录…"
    if (-not (Test-Path (Join-Path $target "runtime\python.exe"))) {
        Show "✘ 不是有效的 RVC 根目录（缺少 runtime\python.exe），请重新选择"
        $r = [System.Windows.Forms.MessageBox]::Show(
            "所选文件夹不是有效的 RVC 根目录：`n$target`n`n缺少 runtime\python.exe。`n是否重新选择？",
            "校验失败", [System.Windows.Forms.MessageBoxButtons]::YesNo,
            [System.Windows.Forms.MessageBoxIcon]::Error)
        if ($r -ne [System.Windows.Forms.DialogResult]::Yes) {
            exit 1
        }
        $target = $null  # 重新选择
    }
}
Show "✔ 已确认 RVC 根目录：$target"

# ── 5. 持久化环境变量 ──
Show ""
Show "[4/8] 保存安装路径…"
[Environment]::SetEnvironmentVariable("XIAOE_RVC_UI_ROOT", $target, "User")
Show "✔ 已保存（下次启动自动识别）"

# ── 6. 目标目录 ──
Show ""
Show "[5/8] 准备目标目录…"
$Dest = Join-Path $target "xiaoe_rvc_ui"
New-Item -ItemType Directory -Force -Path $Dest | Out-Null
Show "✔ 目标目录就绪：$Dest"

# ── 7. 源 == 目标（已在安装位置运行）则跳过复制 ──
Show ""
Show "[6/8] 复制文件…"
$same = ([IO.Path]::GetFullPath($Source)).TrimEnd("\") -ieq ([IO.Path]::GetFullPath($Dest)).TrimEnd("\")
if (-not $same) {
    # 镜像替换应用文件，保留用户数据（config_files / models），排除开发与临时产物
    Show "正在复制文件…"
    robocopy $Source $Dest /MIR /XD config_files models .git __pycache__ /NFL /NDL /NJH /NJS
    $rc = $LASTEXITCODE
    if ($rc -ge 8) {
        Show "✘ 文件复制失败（robocopy 错误码 $rc）"
        exit 1
    }
    Show "✔ 文件复制完成"
} else {
    Show "✔ 已在安装位置，无需复制"
}

# ── 8a. 询问创建桌面快捷方式（PowerShell COM，零依赖）──
Show ""
Show "[7/8] 创建桌面快捷方式…"
$runVbs = Join-Path $Dest "run.vbs"
$r2 = [System.Windows.Forms.MessageBox]::Show(
    "安装完成！xiaoe_rvc_ui 已部署到：`n$Dest`n`n是否创建桌面快捷方式？",
    "xiaoe_rvc_ui 安装器", [System.Windows.Forms.MessageBoxButtons]::YesNo,
    [System.Windows.Forms.MessageBoxIcon]::Question)
if ($r2 -eq [System.Windows.Forms.DialogResult]::Yes) {
    try {
        $icon = Join-Path $Dest "static\logo.ico"
        $lnkName = "RVC实时变声-小娥UI版.lnk"
        $lnkPath = Join-Path ([Environment]::GetFolderPath("Desktop")) $lnkName
        $ws = New-Object -ComObject WScript.Shell
        $lnk = $ws.CreateShortcut($lnkPath)
        $lnk.TargetPath = $runVbs
        $lnk.WorkingDirectory = $Dest
        $lnk.IconLocation = $icon
        $lnk.Save()
        Show "✔ 快捷方式已创建"
    } catch {
        Show "✘ 快捷方式创建失败：$($_.Exception.Message)"
    }
} else {
    Show "已跳过"
}

# ── 8b. 询问打开 run.vbs 启动（自动装依赖）──
Show ""
Show "[8/8] 启动…"
$r3 = [System.Windows.Forms.MessageBox]::Show(
    "是否立即打开 run.vbs 启动？`n（首次运行会自动检查并安装依赖）",
    "xiaoe_rvc_ui 安装器", [System.Windows.Forms.MessageBoxButtons]::YesNo,
    [System.Windows.Forms.MessageBoxIcon]::Question)
if ($r3 -eq [System.Windows.Forms.DialogResult]::Yes) {
    Start-Process -FilePath $runVbs
    Show "正在启动…"
} else {
    Show "已跳过，稍后双击 run.vbs 启动"
}
Show ""
Show "============================================"
Show "   ✔ 安装完成！"
Show "============================================"

} catch {
    Show "✘ 安装出错：$($_.Exception.Message)"
    exit 1
}

exit 0
