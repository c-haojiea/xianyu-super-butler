$ErrorActionPreference = 'SilentlyContinue'
$root = 'D:\software\2026_08_18_After\xianyu-super-butler-main'

Write-Host '=========================================='
Write-Host '  闲鱼超级管家 运行状态检查'
Write-Host ('  检查时间：' + (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'))
Write-Host '=========================================='
Write-Host ''

$conn = Get-NetTCPConnection -LocalPort 8081 -State Listen
if ($conn) {
    $p = Get-Process -Id $conn[0].OwningProcess
    Write-Host ('[OK] 服务正在运行：端口 8081 已监听，PID ' + $conn[0].OwningProcess + '，内存 ' + [math]::Round($p.WorkingSet64 / 1MB, 1) + ' MB') -ForegroundColor Green
} else {
    Write-Host '[X] 服务未运行：端口 8081 没有监听' -ForegroundColor Red
}

try {
    $r = Invoke-WebRequest -Uri 'http://localhost:8081' -UseBasicParsing -TimeoutSec 6
    if ($r.StatusCode -eq 200) {
        Write-Host '[OK] 后台网页正常：http://localhost:8081' -ForegroundColor Green
    } else {
        Write-Host ('[X] 后台网页返回异常状态：' + $r.StatusCode) -ForegroundColor Red
    }
} catch {
    Write-Host '[X] 后台网页打不开' -ForegroundColor Red
}

$task = Get-ScheduledTask -TaskName 'XianyuSuperButler'
if ($task) {
    Write-Host ('[OK] 开机自启任务：' + $task.State) -ForegroundColor Green
} else {
    Write-Host '[!] 开机自启任务不存在' -ForegroundColor Yellow
}

$log = Get-ChildItem (Join-Path $root 'logs\xianyu_*.log') | Sort-Object LastWriteTime -Descending | Select-Object -First 1
if ($log) {
    # 以最近一次真实心跳为准，避免重连日志刷新文件时间造成误判
    $beat = Select-String -Path $log.FullName -Pattern 'handle_heartbeat_response' | Select-Object -Last 1
    if ($beat -and $beat.Line -match '^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})') {
        $beatTime = [datetime]::ParseExact($matches[1], 'yyyy-MM-dd HH:mm:ss', $null)
        $beatMins = [int]((Get-Date) - $beatTime).TotalMinutes
        if ($beatMins -le 3) {
            Write-Host ('[OK] 账号心跳正常：最近心跳 ' + $beatTime.ToString('HH:mm:ss') + '（' + $beatMins + ' 分钟前）') -ForegroundColor Green
        } else {
            Write-Host ('[!] 最近心跳 ' + $beatTime.ToString('HH:mm:ss') + '（' + $beatMins + ' 分钟前），账号可能掉线，请打开后台检查') -ForegroundColor Yellow
        }
    } else {
        Write-Host '[!] 日志中没有心跳记录，账号可能未连接' -ForegroundColor Yellow
    }
} else {
    Write-Host '[!] 找不到运行日志' -ForegroundColor Yellow
}

# 今日经营数据
$py = 'E:\Cyuyan\Python\Python3.12\python.exe'
$dbPath = Join-Path $root 'data\xianyu_data.db'
$statsScript = Join-Path $root 'daily_stats.py'
Write-Host ''
if ((Test-Path $py) -and (Test-Path $dbPath) -and (Test-Path $statsScript)) {
    & $py $statsScript $dbPath
} else {
    Write-Host '[!] 无法读取经营数据' -ForegroundColor Yellow
}

# 待发货订单：离线期间的订单不会自动补发，开机后需要人工检查
$py = 'E:\Cyuyan\Python\Python3.12\python.exe'
$dbPath = Join-Path $root 'data\xianyu_data.db'
if ((Test-Path $py) -and (Test-Path $dbPath)) {
    $raw = & $py (Join-Path $root 'pending_orders_check.py') $dbPath 2>$null
    $pendingText = ($raw | Where-Object { $_ -match '^\d+$' } | Select-Object -First 1)
    if ($pendingText) {
        $pending = [int]$pendingText
        if ($pending -gt 0) {
            Write-Host ('[!] 待发货订单：' + $pending + ' 笔，请打开后台订单页筛选「待发货」并手动发货') -ForegroundColor Yellow
        } else {
            Write-Host '[OK] 待发货订单：0 笔' -ForegroundColor Green
        }
    } else {
        Write-Host '[!] 读取待发货订单失败，请打开后台订单页确认' -ForegroundColor Yellow
    }
} else {
    Write-Host '[!] 找不到订单数据库，跳过待发货检查' -ForegroundColor Yellow
}

Write-Host ''
Write-Host '判断规则：'
Write-Host '  1. 端口 + 网页正常 = 程序在运行'
Write-Host '  2. 最近一次心跳 3 分钟内 = 闲鱼账号在线'
Write-Host '  3. 待发货 0 笔 = 没有漏发订单'
Write-Host '  4. 心跳停了 = 账号掉线，请打开后台重新登录'
Write-Host ''
