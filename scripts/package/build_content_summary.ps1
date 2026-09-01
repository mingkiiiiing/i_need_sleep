$ErrorActionPreference = 'Stop'

$Workspace = 'D:\Project\fuwai'
$OutputRoot = Join-Path $Workspace '内容汇总_2026-08-31'
$DeliverablesDir = Join-Path $OutputRoot '01_实际成果'
$RawDir = Join-Path $OutputRoot '02_原始数据'
$ExcludedDir = Join-Path $OutputRoot '03_排除说明'

New-Item -ItemType Directory -Force -Path $DeliverablesDir, $RawDir, $ExcludedDir | Out-Null

function Get-RelativePath([string]$Base, [string]$Path) {
    return [IO.Path]::GetRelativePath($Base, $Path)
}

function Get-Category([string]$RelativePath) {
    $p = $RelativePath -replace '/', '\'
    if ($p -match '(^|\\)src\\|(^|\\)(index|cockpit|demo-flow|heatmap|history|project-overview|stations|tech-route)\.html$|(^|\\)(styles\.css|script\.js)$') { return '前端与数字孪生驾驶舱' }
    if ($p -match '(^|\\)backend\\') { return '后端接口与联调' }
    if ($p -match '(^|\\)data-cleaning\\') { return '数据工程代码、配置、测试与文档' }
    if ($p -match '里程碑7_成员C机理AI融合建模') { return '机理-AI融合建模框架' }
    if ($p -match '(^|\\)reports\\') { return '审计与正式报告' }
    if ($p -match '(^|\\)design-export\\') { return '设计导出' }
    if ($p -match '(^|\\)dist\\') { return '构建产物' }
    if ($p -match '(^|\\)(README|INTEGRATION|A23|codex-handoff-summary).*\.(md|txt)$') { return '项目说明与交接文档' }
    if ($p -match '\.(py|ps1|js|cjs|vue|css|html|yml|yaml|toml|json)$') { return '代码与工程配置' }
    return '其他项目成果'
}

$deliverableRoots = @(
    [pscustomobject]@{ Path = Join-Path $Workspace '2026_sheng-fuwai-main-merge'; Version = '当前主合并版本' },
    [pscustomobject]@{ Path = Join-Path $Workspace '2026_sheng-fuwai'; Version = '早期版本' }
)

$deliverables = foreach ($root in $deliverableRoots) {
    Get-ChildItem -LiteralPath $root.Path -Recurse -File -Force -ErrorAction SilentlyContinue |
        Where-Object {
            $rel = Get-RelativePath $root.Path $_.FullName
            $rel -notmatch '(^|\\)(\.git|node_modules|\.pytest_cache|__pycache__|tmp)(\\|$)' -and
            $rel -notmatch '(^|\\)data-cleaning\\storage(\\|$)' -and
            $rel -notmatch '(^|\\)(raw|cleaned|processed|silver|rasters|runs|exports)(\\|$)' -and
            $_.Name -notmatch '\.(pyc|log)$' -and
            $_.Name -notmatch '^\.env(?!\.example$)'
        } |
        ForEach-Object {
            $rel = Get-RelativePath $root.Path $_.FullName
            [pscustomobject]@{
                版本 = $root.Version
                类别 = Get-Category $rel
                相对路径 = $rel
                完整路径 = $_.FullName
                扩展名 = $_.Extension.ToLowerInvariant()
                字节数 = $_.Length
                修改时间 = $_.LastWriteTime.ToString('yyyy-MM-dd HH:mm:ss')
            }
        }
}

# 数据检索目录中的脚本属于实际工作；抓取响应本身归入原始数据。
$collectionScripts = Get-ChildItem -LiteralPath (Join-Path $Workspace 'lake_data_tmp') -File -ErrorAction SilentlyContinue |
    Where-Object { $_.Extension -in @('.py', '.js') -and $_.Name -in @('fetch_details.py', 'parse_cat.py', 'parse_pages.py') } |
    ForEach-Object {
        [pscustomobject]@{
            版本 = '数据检索辅助工具'
            类别 = '原始数据采集工具'
            相对路径 = Get-RelativePath $Workspace $_.FullName
            完整路径 = $_.FullName
            扩展名 = $_.Extension.ToLowerInvariant()
            字节数 = $_.Length
            修改时间 = $_.LastWriteTime.ToString('yyyy-MM-dd HH:mm:ss')
        }
    }
$deliverables = @($deliverables) + @($collectionScripts)
$deliverables | Sort-Object 版本, 类别, 相对路径 | Export-Csv -LiteralPath (Join-Path $DeliverablesDir '实际成果清单.csv') -NoTypeInformation -Encoding utf8BOM

$rawSources = @(
    [pscustomobject]@{ Path = Join-Path $Workspace 'merged_data\2026_sheng-fuwai-main-merge\raw'; Group = '当前主原始数据区'; Note = '优先使用；主合并版本的不可变原始数据' },
    [pscustomobject]@{ Path = Join-Path $Workspace 'merged_data\2026_sheng-fuwai\raw'; Group = '旧版原始数据区'; Note = '历史采集快照；可能与主原始区重复' },
    [pscustomobject]@{ Path = Join-Path $Workspace 'merged_data\2026_sheng-fuwai\THQBCA-V2'; Group = 'THQBCA-V2原始数据集（解压）'; Note = '原始数据集解压目录' },
    [pscustomobject]@{ Path = Join-Path $Workspace 'merged_data\2026_sheng-fuwai\THQBCA-V2.rar'; Group = 'THQBCA-V2原始压缩包'; Note = '原始压缩包' },
    [pscustomobject]@{ Path = Join-Path $Workspace 'lake_data_tmp'; Group = '数据目录检索原始响应'; Note = '公开数据目录检索/详情响应；采集脚本另列为成果' }
)

$rawRows = foreach ($source in $rawSources) {
    if (-not (Test-Path -LiteralPath $source.Path)) { continue }
    $item = Get-Item -LiteralPath $source.Path
    $files = if ($item.PSIsContainer) {
        Get-ChildItem -LiteralPath $source.Path -Recurse -File -Force -ErrorAction SilentlyContinue
    } else {
        @($item)
    }
    foreach ($file in $files) {
        $rel = if ($item.PSIsContainer) { Get-RelativePath $source.Path $file.FullName } else { $file.Name }
        # 旧原始区中明确标注 parsed 的历史转换件不作为原始数据交付。
        if ($source.Group -eq '旧版原始数据区' -and $rel -match '(^|\\).*parsed(\\|$)') { continue }
        # 数据检索目录中的自编脚本不属于原始响应。
        if ($source.Group -eq '数据目录检索原始响应' -and $file.Name -in @('fetch_details.py', 'parse_cat.py', 'parse_pages.py')) { continue }
        $collection = if (-not $item.PSIsContainer) {
            $source.Group
        } elseif ($source.Group -eq '数据目录检索原始响应') {
            '公开数据目录检索响应'
        } elseif ($rel -match '^[^\\]+') {
            ($rel -split '\\')[0]
        } else {
            $source.Group
        }
        [pscustomobject]@{
            原始数据组 = $source.Group
            数据集合 = $collection
            组内相对路径 = $rel
            完整路径 = $file.FullName
            扩展名 = $file.Extension.ToLowerInvariant()
            字节数 = $file.Length
            修改时间 = $file.LastWriteTime.ToString('yyyy-MM-dd HH:mm:ss')
            说明 = $source.Note
        }
    }
}
$rawRows = @($rawRows)
$rawRows | Sort-Object 原始数据组, 数据集合, 组内相对路径 | Export-Csv -LiteralPath (Join-Path $RawDir '原始数据清单.csv') -NoTypeInformation -Encoding utf8BOM

$rawSummary = $rawRows | Group-Object 原始数据组, 数据集合 | ForEach-Object {
    $sample = $_.Group[0]
    [pscustomobject]@{
        原始数据组 = $sample.原始数据组
        数据集合 = $sample.数据集合
        文件数 = $_.Count
        字节数 = ($_.Group | Measure-Object 字节数 -Sum).Sum
        大小GB = [math]::Round((($_.Group | Measure-Object 字节数 -Sum).Sum / 1GB), 3)
        说明 = $sample.说明
    }
}
$rawSummary | Sort-Object 原始数据组, 数据集合 | Export-Csv -LiteralPath (Join-Path $RawDir '原始数据分组统计.csv') -NoTypeInformation -Encoding utf8BOM

$deliverableGroups = $deliverables | Group-Object 版本, 类别 | ForEach-Object {
    $sample = $_.Group[0]
    "| $($sample.版本) | $($sample.类别) | $($_.Count) |"
}
$rawGroupLines = $rawRows | Group-Object 原始数据组 | ForEach-Object {
    $bytes = ($_.Group | Measure-Object 字节数 -Sum).Sum
    "| $($_.Name) | $($_.Count) | $([math]::Round($bytes / 1GB, 3)) |"
}

$rootReadme = @"
# 项目内容汇总（2026-08-31）

本目录把现有项目内容分为两部分：**实际成果**与**全部原始数据**。为避免重复占用约百 GB 空间，本汇总采用“清单 + 原文件绝对路径”的方式，不复制、不移动、不删除原文件。

## 1. 实际成果

- 当前主合并版本：前端数字孪生驾驶舱、FastAPI 后端、联调契约、数据工程代码/配置/测试/文档、成员 C 机理-AI 融合建模框架、设计导出和审计报告。
- 早期版本：静态多页面站点、早期数据工程实现及相关说明，作为历史成果保留。
- 数据检索辅助工具：公开数据目录检索和解析脚本。
- 逐文件明细见 01_实际成果/实际成果清单.csv。

| 版本 | 类别 | 文件数 |
| --- | --- | ---: |
$($deliverableGroups -join "`n")

## 2. 原始数据

- 当前主原始数据区为优先来源。
- 旧版原始数据区保留历史采集快照，其中可能有重复文件。
- THQBCA-V2 同时保留原始压缩包和解压目录。
- 数据目录检索的原始 JSON/TXT/CSV/网页脚本响应一并收录。
- 逐文件明细见 02_原始数据/原始数据清单.csv，分组统计见 02_原始数据/原始数据分组统计.csv。

| 原始数据组 | 文件数 | 大小（GB） |
| --- | ---: | ---: |
$($rawGroupLines -join "`n")

## 3. 明确未纳入

按要求，历史清洗及衍生数据未进入成果或原始数据交付清单，包括路径中的 cleaned、processed、silver、rasters、runs、exports，以及旧原始区中明确标注 parsed 的转换件。依赖、缓存与临时调试文件也未纳入。详见 03_排除说明/README.md。

## 使用方式

CSV 中的“完整路径”可直接定位现有文件。若后续需要形成可移动的完整交付包，建议先按清单去重，再复制到独立磁盘；当前汇总本身不会造成大体积重复。
"@
Set-Content -LiteralPath (Join-Path $OutputRoot 'README.md') -Value $rootReadme -Encoding utf8BOM

$deliverablesReadme = @"
# 实际成果

本目录只保存成果索引，不重复复制工程文件。权威开发版本是：

- D:\Project\fuwai\2026_sheng-fuwai-main-merge

早期版本是：

- D:\Project\fuwai\2026_sheng-fuwai

成果清单已排除 Git 元数据、依赖目录、缓存、临时目录、历史清洗数据、日志、字节码与潜在凭据文件。
"@
Set-Content -LiteralPath (Join-Path $DeliverablesDir 'README.md') -Value $deliverablesReadme -Encoding utf8BOM

$rawReadme = @"
# 原始数据

原始数据逐文件清单包含主原始区、旧版原始区、THQBCA-V2 原包及解压件，以及公开数据目录检索的原始响应。主原始区优先；旧版区用于补充追溯，可能存在重复。

本目录没有复制原始数据文件。请根据 CSV 的“完整路径”访问原件。
"@
Set-Content -LiteralPath (Join-Path $RawDir 'README.md') -Value $rawReadme -Encoding utf8BOM

$excludedReadme = @"
# 排除说明

以下内容未纳入本次汇总交付：

- 历史清洗数据：cleaned/、processed/；
- 中间层与衍生栅格：silver/、rasters/；
- 流水线运行产物与导出：runs/、exports/；
- 旧原始区中名称明确带 parsed 的转换件；
- 依赖与缓存：node_modules/、.pytest_cache/、__pycache__/；
- Git 元数据、临时目录、日志、字节码；
- .env 等可能包含访问凭据的文件；
- 根目录验证码截图等临时采集调试图片。

这些文件没有被删除，只是没有进入本次成果/原始数据清单。
"@
Set-Content -LiteralPath (Join-Path $ExcludedDir 'README.md') -Value $excludedReadme -Encoding utf8BOM

Write-Output "Output: $OutputRoot"
Write-Output "Deliverable files: $($deliverables.Count)"
Write-Output "Raw files: $($rawRows.Count)"
Write-Output "Raw size GB: $([math]::Round((($rawRows | Measure-Object 字节数 -Sum).Sum / 1GB), 3))"
