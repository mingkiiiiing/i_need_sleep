$ErrorActionPreference = 'Stop'

$Workspace = 'D:\Project\fuwai'
$MainRepo = Join-Path $Workspace '2026_sheng-fuwai-main-merge'
$LegacyRepo = Join-Path $Workspace '2026_sheng-fuwai'
$MergedMain = Join-Path $Workspace 'merged_data\2026_sheng-fuwai-main-merge'
$MergedLegacy = Join-Path $Workspace 'merged_data\2026_sheng-fuwai'
$Target = Join-Path $Workspace '项目完整汇总_2026-08-31'
$Dev = Join-Path $Target '01_我们的开发'
$Raw = Join-Path $Target '02_全部原始数据'

$OldDev = Join-Path $Target '01_开发成果'
$DevStaging = Join-Path $Target '01_我们的开发_正在生成'
if (Test-Path -LiteralPath $DevStaging) {
    Remove-Item -LiteralPath $DevStaging -Recurse -Force
}
New-Item -ItemType Directory -Path $DevStaging, $Raw -Force | Out-Null

$script:LinkedFiles = 0
$script:CopiedFiles = 0
$script:TotalBytes = [int64]0

function Add-File([string]$Source, [string]$Destination) {
    if (-not (Test-Path -LiteralPath $Source -PathType Leaf)) { return }
    if (Test-Path -LiteralPath $Destination -PathType Leaf) { return }
    try {
        $sourceItem = Get-Item -LiteralPath $Source -ErrorAction Stop
    } catch {
        return
    }
    $parent = Split-Path -Parent $Destination
    if (-not (Test-Path -LiteralPath $parent)) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }
    try {
        New-Item -ItemType HardLink -Path $Destination -Target $Source -ErrorAction Stop | Out-Null
        $script:LinkedFiles++
    } catch {
        Copy-Item -LiteralPath $Source -Destination $Destination -Force
        $script:CopiedFiles++
    }
    $script:TotalBytes += $sourceItem.Length
}

function Add-Tree(
    [string]$SourceRoot,
    [string]$DestinationRoot,
    [string[]]$ExcludePatterns = @(),
    [string[]]$IncludeExtensions = @()
) {
    if (-not (Test-Path -LiteralPath $SourceRoot)) { return }
    Get-ChildItem -LiteralPath $SourceRoot -Recurse -File -Force -ErrorAction SilentlyContinue | ForEach-Object {
        $relative = [IO.Path]::GetRelativePath($SourceRoot, $_.FullName)
        foreach ($pattern in $ExcludePatterns) {
            if ($relative -match $pattern) { return }
        }
        if ($IncludeExtensions.Count -gt 0 -and $_.Extension.ToLowerInvariant() -notin $IncludeExtensions) { return }
        Add-File $_.FullName (Join-Path $DestinationRoot $relative)
    }
}

function Add-SelectedFiles([string]$SourceRoot, [string]$DestinationRoot, [string[]]$Names) {
    foreach ($name in $Names) {
        $source = Join-Path $SourceRoot $name
        if (Test-Path -LiteralPath $source -PathType Leaf) {
            Add-File $source (Join-Path $DestinationRoot $name)
        }
    }
}

$commonExcludes = @(
    '(^|\\)\.git(\\|$)',
    '(^|\\)node_modules(\\|$)',
    '(^|\\)\.pytest_cache(\\|$)',
    '(^|\\)__pycache__(\\|$)',
    '(^|\\)tmp(\\|$)',
    '\.pyc$',
    '\.log$',
    '(^|\\)\.env(?!\.example$)'
)

# 01 我们的开发：保持原工程为一个整体，不再拆分前端、后端、算法和清洗代码。
# 最新主工程优先；旧工程只补充主工程中不存在的文件，并保持原相对路径。
$developmentExcludes = @($commonExcludes) + @(
    '(^|\\)data-cleaning\\storage(\\|$)',
    '(^|\\)cleaned(\\|$)',
    '(^|\\)processed(\\|$)',
    '(^|\\)silver(\\|$)',
    '(^|\\)rasters(\\|$)',
    '(^|\\)runs(\\|$)',
    '(^|\\)exports(\\|$)',
    '(^|\\)\.dev-backend\.err$',
    '(^|\\)backend_log\.txt$',
    '(^|\\)uv\.(err|out)$'
)
Add-Tree $MainRepo $DevStaging $developmentExcludes
Add-Tree $LegacyRepo $DevStaging $developmentExcludes

# 原始数据目录检索脚本也是项目代码，放回统一工程的 scripts 下。
foreach ($name in @('fetch_details.py','parse_cat.py','parse_pages.py')) {
    $source = Join-Path $Workspace "lake_data_tmp\$name"
    if (Test-Path -LiteralPath $source) {
        Add-File $source (Join-Path $DevStaging "scripts\raw_catalog\$name")
    }
}
foreach ($name in @('build_content_summary.ps1','build_full_package.ps1')) {
    $source = Join-Path $Workspace $name
    if (Test-Path -LiteralPath $source) {
        Add-File $source (Join-Path $DevStaging "scripts\package\$name")
    }
}

# 部分早期采集/处理代码随数据存储区迁出，必须补回统一工程。
Add-Tree (Join-Path $MergedMain 'scripts') (Join-Path $DevStaging 'data-cleaning\storage\scripts') $commonExcludes

# 完整保留当前数据工程的历史计算成果，并放回程序预期的 storage 结构。
foreach ($name in @('cleaned','exports','manifests','processed','rasters','reports','scripts','silver')) {
    Add-Tree (Join-Path $MergedMain $name) (Join-Path $DevStaging "data-cleaning\storage\$name") $commonExcludes
}
Add-Tree (Join-Path $MergedMain 'reports') (Join-Path $DevStaging 'data-cleaning\storage\reports') @()
Add-Tree (Join-Path $MainRepo 'data-cleaning\storage\cleaned') (Join-Path $DevStaging 'data-cleaning\storage\cleaned') $commonExcludes
Add-Tree (Join-Path $MainRepo 'data-cleaning\scripts\logs') (Join-Path $DevStaging 'data-cleaning\storage\logs\source_scripts') @()

# 旧版的数据库、发布包、黄金表、运行记录及其他计算结果作为完整历史快照保留。
$legacySnapshot = Join-Path $DevStaging 'data-cleaning\storage\legacy_snapshot'
foreach ($name in @('databases','exports','gold','rasters','releases','reports','runs','silver','staging')) {
    Add-Tree (Join-Path $MergedLegacy $name) (Join-Path $legacySnapshot $name) $commonExcludes
}
Add-Tree (Join-Path $LegacyRepo 'data-cleaning\storage\cleaned') (Join-Path $legacySnapshot 'repo_cleaned') $commonExcludes
Add-Tree (Join-Path $MainRepo 'dist') (Join-Path $legacySnapshot 'frontend_dist\current_prebuild') @()
Add-Tree (Join-Path $LegacyRepo 'dist') (Join-Path $legacySnapshot 'frontend_dist\legacy') @()
$legacyDatabase = Join-Path $MergedLegacy 'data_cleaning.db'
if (Test-Path -LiteralPath $legacyDatabase) {
    Add-File $legacyDatabase (Join-Path $legacySnapshot 'data_cleaning.db')
}

# 前端依赖也并入统一工程，避免删除旧工程后立即无法启动。
Add-Tree (Join-Path $MainRepo 'node_modules') (Join-Path $DevStaging 'node_modules') @()
Add-Tree (Join-Path $LegacyRepo 'node_modules') (Join-Path $DevStaging 'node_modules') @()

# 授权回执和已有下载凭据单独放入 private，避免与普通代码混淆。
$privateDir = Join-Path $DevStaging 'private'
Add-Tree (Join-Path $MergedMain 'authorization') (Join-Path $privateDir 'authorization') @()
Add-Tree (Join-Path $MergedMain 'authorization') (Join-Path $DevStaging 'data-cleaning\storage\authorization') @()
foreach ($entry in @(
    [pscustomobject]@{ Source = Join-Path $MainRepo 'data-cleaning\.env.cdse'; Name = 'current.env.cdse' },
    [pscustomobject]@{ Source = Join-Path $LegacyRepo 'data-cleaning\.env.cdse'; Name = 'legacy.env.cdse' }
)) {
    if (Test-Path -LiteralPath $entry.Source) {
        Add-File $entry.Source (Join-Path $privateDir "credentials\$($entry.Name)")
    }
}

# 用可移植 Git bundle 保留提交历史；工作区当前文件本身已由上面的统一工程收录。
$historyDir = Join-Path $DevStaging 'history'
New-Item -ItemType Directory -Path $historyDir -Force | Out-Null
& git -C $MainRepo bundle create (Join-Path $historyDir 'main-repository-history.bundle') --all
if ($LASTEXITCODE -ne 0) { throw 'Failed to create main repository Git bundle.' }
& git -C $LegacyRepo bundle create (Join-Path $historyDir 'legacy-repository-history.bundle') --all
if ($LASTEXITCODE -ne 0) { throw 'Failed to create legacy repository Git bundle.' }
(& git -C $MainRepo status --short --branch) | Set-Content -LiteralPath (Join-Path $historyDir 'main-working-tree-status.txt') -Encoding utf8BOM
(& git -C $LegacyRepo status --short --branch) | Set-Content -LiteralPath (Join-Path $historyDir 'legacy-working-tree-status.txt') -Encoding utf8BOM

$devReadme = @'
# 我们的开发（统一工程）

这里是一套完整工程，不再按“前端 / 后端 / 算法 / 数据清洗”拆成彼此独立的归档。

- 主体来自最新开发目录 `2026_sheng-fuwai-main-merge`；
- 旧开发目录 `2026_sheng-fuwai` 中主工程没有的文件，已按原相对路径补入；
- `src`、`backend`、`data-cleaning`、算法目录、配置、测试、报告和项目文档保持在同一个项目根目录；
- 大体积原始数据统一放在同级的 `02_全部原始数据`，没有混进程序目录；
- 历史计算成果、数据库、发布包、栅格资产、前端依赖和必要授权资料均已纳入；Git 提交历史保存在 `history` 中的可移植 bundle。授权资料位于 `private`，复制或分享前需谨慎处理。

本目录是整理后的唯一完整工程；旧工作目录核验后可由本汇总替代。
'@
Set-Content -LiteralPath (Join-Path $DevStaging 'README_统一工程说明.md') -Value $devReadme -Encoding utf8BOM

# 新工程生成完整后再切换，避免留下半成品。旧拆分目录只含汇总副本，源工程不受影响。
if (Test-Path -LiteralPath $Dev) {
    Remove-Item -LiteralPath $Dev -Recurse -Force
}
Move-Item -LiteralPath $DevStaging -Destination $Dev
if (Test-Path -LiteralPath $OldDev) {
    Remove-Item -LiteralPath $OldDev -Recurse -Force
}

# 02 全部原始数据：当前主原始区。
Add-Tree (Join-Path $MergedMain 'raw') (Join-Path $Raw '01_当前主原始数据') @()

# 旧版原始区作为补充历史采集；明确 parsed 的转换件不纳入。
Add-Tree (Join-Path $MergedLegacy 'raw') (Join-Path $Raw '02_旧版补充原始数据') @('(^|\\).*parsed(\\|$)')

# THQBCA-V2 原始数据集压缩包与原始解压内容。
Add-Tree (Join-Path $MergedLegacy 'THQBCA-V2') (Join-Path $Raw '03_THQBCA-V2原始数据集\解压内容') @()
$thqbcaArchive = Join-Path $MergedLegacy 'THQBCA-V2.rar'
if (Test-Path -LiteralPath $thqbcaArchive) {
    Add-File $thqbcaArchive (Join-Path $Raw '03_THQBCA-V2原始数据集\THQBCA-V2.rar')
}

# 公开数据目录检索时保存的原始响应；自编解析脚本已放入开发成果。
Add-Tree (Join-Path $Workspace 'lake_data_tmp') (Join-Path $Raw '04_公开数据目录检索原始响应') @(
    '(^|\\)(fetch_details|parse_cat|parse_pages)\.py$'
)

# 旧版 raw_organized 同时包含原始副本、补充采集、已解析文件和派生文件。
# 在彻底清理旧目录前整区保留，避免仅凭目录名误删唯一数据。
Add-Tree (Join-Path $MergedLegacy 'raw_organized') (Join-Path $Raw '05_旧版整理区_混合留存') @(
    '(^|\\)Thumbs\.db$',
    '(^|\\)~\$'
)

# 采集清单是判断来源、时间、授权状态和失败原因所需的原始数据伴随元数据。
Add-Tree (Join-Path $MergedMain 'manifests') (Join-Path $Raw '06_主数据采集与来源清单') @()
$sourceVerification = Join-Path $MainRepo 'data-cleaning\data-cleaning\storage\manifests\source_verification.json'
if (Test-Path -LiteralPath $sourceVerification) {
    Add-File $sourceVerification (Join-Path $Raw '06_主数据采集与来源清单\repo_source_verification.json')
}

# 根目录验证码图片属于采集过程原始留痕，统一归入原始数据区。
$captureTemp = Join-Path $Raw '07_采集过程临时资料'
Get-ChildItem -LiteralPath $Workspace -File -Force | Where-Object {
    $_.Name -match '^(captcha|geodata_captcha).*\.(jpg|png)$'
} | ForEach-Object {
    Add-File $_.FullName (Join-Path $captureTemp $_.Name)
}

# 程序仍通过 data-cleaning/storage/raw 访问主原始区；使用目录联接避免再复制一份。
$rawLink = Join-Path $Dev 'data-cleaning\storage\raw'
if (-not (Test-Path -LiteralPath $rawLink)) {
    New-Item -ItemType Junction -Path $rawLink -Target (Join-Path $Raw '01_当前主原始数据') | Out-Null
}

$devFiles = @(Get-ChildItem -LiteralPath $Dev -Recurse -File -Force)
$rawFiles = @(Get-ChildItem -LiteralPath $Raw -Recurse -File -Force)
$devBytes = ($devFiles | Measure-Object Length -Sum).Sum
$rawBytes = ($rawFiles | Measure-Object Length -Sum).Sum

$readme = @"
# 项目完整汇总

本目录仅分为两大部分：

1. 01_我们的开发：保持原始相对路径的一体化完整工程；
2. 02_全部原始数据：当前主原始区、旧版补充原始区、THQBCA-V2、公开数据目录检索响应、旧版整理区的混合留存副本，以及采集与来源清单。

## 数量

- 我们的开发：$($devFiles.Count) 个文件，$([math]::Round($devBytes / 1GB, 3)) GB；
- 原始数据：$($rawFiles.Count) 个文件，$([math]::Round($rawBytes / 1GB, 3)) GB。

## 排除内容

开发部分不再拆分，前端、后端、算法、数据清洗代码、测试、报告和文档仍位于同一工程根目录；迁入数据区的采集/处理脚本、历史 cleaned/processed/silver/gold/rasters/runs/exports、数据库、发布包和前端依赖也已归入统一工程。Git 历史以 bundle 形式保留，授权资料单独放在 private。旧版 raw_organized 因混合包含原始副本和派生文件，已整区保留以防误删唯一数据。

## 文件存储说明

本汇总中的文件均可直接打开读取。为避免重复占用大体积磁盘空间，同一 D 盘内优先采用 NTFS 硬链接；若硬链接失败则自动复制。将本目录复制到移动硬盘或其他磁盘时，系统会按普通完整文件复制。
"@
Set-Content -LiteralPath (Join-Path $Target 'README.md') -Value $readme -Encoding utf8BOM

[pscustomobject]@{
    Target = $Target
    DevelopmentFiles = $devFiles.Count
    DevelopmentGB = [math]::Round($devBytes / 1GB, 3)
    RawFiles = $rawFiles.Count
    RawGB = [math]::Round($rawBytes / 1GB, 3)
    HardLinkedFiles = $script:LinkedFiles
    CopiedFiles = $script:CopiedFiles
    LogicalTotalGB = [math]::Round($script:TotalBytes / 1GB, 3)
} | Format-List
