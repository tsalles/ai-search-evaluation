param(
    [Parameter(Mandatory=$true)][string]$InputPath,
    [Parameter(Mandatory=$true)][string]$OutputDirectory
)
$ErrorActionPreference='Stop'
$source=(Get-Item -LiteralPath $InputPath).FullName
$extension=[System.IO.Path]::GetExtension($source).ToLowerInvariant()
if ($extension -notin @('.docx','.pptx','.xlsx')) { throw 'Preview supports DOCX, PPTX, and XLSX.' }
New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
$destination=Join-Path (Get-Item -LiteralPath $OutputDirectory).FullName (
    [System.IO.Path]::GetFileNameWithoutExtension($source)+$extension+'.pdf'
)
if (Test-Path -LiteralPath $destination) { throw 'Preview already exists; nothing was overwritten.' }
Add-Type @'
using System;
using System.Runtime.InteropServices;
public static class DocgenWindowOwner {
    [DllImport("user32.dll")]
    public static extern uint GetWindowThreadProcessId(IntPtr hwnd, out uint processId);
}
'@
$processName=@{'.docx'='WINWORD';'.pptx'='POWERPNT';'.xlsx'='EXCEL'}[$extension]
$before=@(Get-Process -Name $processName -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id)
$application=$null
$document=$null
$owned=$false
try {
    $class=@{'.docx'='Word.Application';'.pptx'='PowerPoint.Application';'.xlsx'='Excel.Application'}[$extension]
    $application=New-Object -ComObject $class
    [uint32]$ownerId=0
    $handle=if ($extension -eq '.pptx') { $application.HWND } else { $application.Hwnd }
    if ($null -ne $handle) {
        [DocgenWindowOwner]::GetWindowThreadProcessId([IntPtr]$handle,[ref]$ownerId) | Out-Null
    }
    if ($ownerId -eq 0) {
        $created=@(Get-Process -Name $processName -ErrorAction SilentlyContinue |
            Where-Object { $_.Id -notin $before } | Select-Object -ExpandProperty Id)
        if ($created.Count -eq 1) { $ownerId=$created[0] }
    }
    $owned=$ownerId -ne 0 -and $ownerId -notin $before
    if ($extension -eq '.docx') {
        if ($owned) { $application.Visible=$false; $application.DisplayAlerts=0 }
        $document=$application.Documents.Open($source,$false,$true)
        $document.ExportAsFixedFormat($destination,17)
    } elseif ($extension -eq '.pptx') {
        $document=$application.Presentations.Open($source,-1,0,0)
        $document.SaveAs($destination,32)
    } else {
        if ($owned) { $application.Visible=$false; $application.DisplayAlerts=$false }
        $document=$application.Workbooks.Open($source,0,$true)
        foreach ($sheet in $document.Worksheets) {
            $sheet.PageSetup.Orientation=2
            $sheet.PageSetup.Zoom=$false
            $sheet.PageSetup.FitToPagesWide=1
            $sheet.PageSetup.FitToPagesTall=$false
        }
        $document.ExportAsFixedFormat(0,$destination)
    }
    if (-not (Test-Path -LiteralPath $destination)) { throw 'Native Office did not produce a PDF.' }
    Write-Output $destination
} finally {
    if ($null -ne $document) {
        if ($extension -eq '.pptx') { $document.Close() }
        else { $document.Close($false) }
        [System.Runtime.InteropServices.Marshal]::FinalReleaseComObject($document) | Out-Null
    }
    if ($null -ne $application) {
        $count=if ($extension -eq '.docx') { $application.Documents.Count }
               elseif ($extension -eq '.pptx') { $application.Presentations.Count }
               else { $application.Workbooks.Count }
        if ($owned -and $count -eq 0) { $application.Quit() }
        [System.Runtime.InteropServices.Marshal]::FinalReleaseComObject($application) | Out-Null
    }
}
