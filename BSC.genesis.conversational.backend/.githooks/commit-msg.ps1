param(
    [Parameter(Mandatory = $true)]
    [string]$CommitMsgFile
)

$ErrorActionPreference = "Stop"

# ============================================================
# Configuración
# ============================================================

# Tipos permitidos según Conventional Commits
$AllowedTypes = @(
    "feat",
    "fix",
    "chore",
    "docs",
    "refactor",
    "test",
    "ci",
    "build",
    "perf",
    "style",
    "revert"
)

# Requiere Work Item de Azure Boards tipo AB#12345
$RequireWorkItem = $true

# Largo máximo recomendado para la primera línea
$MaxSubjectLength = 100

# Patrones de Work Item permitidos
$WorkItemRegex = "AB#[0-9]+"

# Mensajes genéricos no permitidos
$BlockedSubjects = @(
    "update",
    "updates",
    "change",
    "changes",
    "fix",
    "fixes",
    "test",
    "prueba",
    "cambios",
    "ajustes",
    "varios",
    "wip"
)

# ============================================================
# Lectura del mensaje
# ============================================================

if (!(Test-Path $CommitMsgFile)) {
    Write-Host "ERROR: No se encontró el archivo del mensaje de commit." -ForegroundColor Red
    exit 1
}

$RawMessage = Get-Content $CommitMsgFile -Raw

if ([string]::IsNullOrWhiteSpace($RawMessage)) {
    Write-Host "ERROR: El mensaje de commit está vacío." -ForegroundColor Red
    exit 1
}

# Eliminar comentarios generados por Git
$MessageLines = $RawMessage -split "`r?`n" | Where-Object {
    $_ -notmatch "^\s*#"
}

$Message = ($MessageLines -join "`n").Trim()

if ([string]::IsNullOrWhiteSpace($Message)) {
    Write-Host "ERROR: El mensaje de commit está vacío." -ForegroundColor Red
    exit 1
}

$FirstLine = ($Message -split "`r?`n")[0].Trim()

# ============================================================
# Permitir commits automáticos de Git
# ============================================================

if ($FirstLine -match "^Merge " -or
    $FirstLine -match "^Revert " -or
    $FirstLine -match "^revert:" -or
    $FirstLine -match "^fixup!" -or
    $FirstLine -match "^squash!") {

    Write-Host "Commit automático detectado. Validación omitida: $FirstLine" -ForegroundColor Yellow
    exit 0
}

# ============================================================
# Validación Conventional Commit
# Formatos válidos:
# feat: mensaje AB#12345
# fix(api): mensaje AB#12345
# feat(auth)!: cambio breaking AB#12345
# ============================================================

$TypesRegex = ($AllowedTypes -join "|")

$ConventionalRegex = "^(?<type>$TypesRegex)(\((?<scope>[a-zA-Z0-9._-]+)\))?(?<breaking>!)?: (?<subject>.+)$"

if ($FirstLine -notmatch $ConventionalRegex) {
    Write-Host ""
    Write-Host "ERROR: Mensaje de commit inválido." -ForegroundColor Red
    Write-Host ""
    Write-Host "Formato esperado:" -ForegroundColor Yellow
    Write-Host "  tipo(scope): descripción AB#12345"
    Write-Host ""
    Write-Host "Ejemplos válidos:" -ForegroundColor Yellow
    Write-Host "  feat(auth): agregar login con Azure AD AB#12345"
    Write-Host "  fix(api): corregir timeout en consulta de clientes AB#12345"
    Write-Host "  chore(pipeline): actualizar tarea de build AB#12345"
    Write-Host "  feat(auth)!: cambiar flujo de autenticación AB#12345"
    Write-Host ""
    Write-Host "Tipos permitidos:" -ForegroundColor Yellow
    Write-Host "  $($AllowedTypes -join ', ')"
    Write-Host ""
    Write-Host "Mensaje recibido:" -ForegroundColor Yellow
    Write-Host "  $FirstLine"
    exit 1
}

$CommitType = $Matches["type"]
$Scope = $Matches["scope"]
$Subject = $Matches["subject"].Trim()

# ============================================================
# Validación de longitud
# ============================================================

if ($FirstLine.Length -gt $MaxSubjectLength) {
    Write-Host ""
    Write-Host "ERROR: La primera línea del commit es demasiado larga." -ForegroundColor Red
    Write-Host "Máximo permitido: $MaxSubjectLength caracteres"
    Write-Host "Longitud actual: $($FirstLine.Length)"
    Write-Host ""
    Write-Host "Mensaje recibido:" -ForegroundColor Yellow
    Write-Host "  $FirstLine"
    exit 1
}

# ============================================================
# Validación de Work Item Azure DevOps
# ============================================================

if ($RequireWorkItem -and $Message -notmatch $WorkItemRegex) {
    Write-Host ""
    Write-Host "ERROR: El commit debe incluir un Work Item de Azure Boards." -ForegroundColor Red
    Write-Host ""
    Write-Host "Formato requerido:" -ForegroundColor Yellow
    Write-Host "  AB#12345"
    Write-Host ""
    Write-Host "Ejemplo:" -ForegroundColor Yellow
    Write-Host "  fix(api): corregir validación de token AB#12345"
    exit 1
}

# ============================================================
# Bloquear subjects genéricos
# ============================================================

$NormalizedSubject = $Subject.ToLower().Trim()

foreach ($Blocked in $BlockedSubjects) {
    if ($NormalizedSubject -eq $Blocked) {
        Write-Host ""
        Write-Host "ERROR: El subject del commit es demasiado genérico." -ForegroundColor Red
        Write-Host ""
        Write-Host "Subject recibido:" -ForegroundColor Yellow
        Write-Host "  $Subject"
        Write-Host ""
        Write-Host "Usa una descripción clara, por ejemplo:" -ForegroundColor Yellow
        Write-Host "  fix(api): corregir error 500 al consultar cliente AB#12345"
        exit 1
    }
}

# ============================================================
# Evitar punto final en el subject
# ============================================================

if ($Subject.EndsWith(".")) {
    Write-Host ""
    Write-Host "ERROR: El subject no debe terminar en punto." -ForegroundColor Red
    Write-Host ""
    Write-Host "Actual:" -ForegroundColor Yellow
    Write-Host "  $FirstLine"
    Write-Host ""
    Write-Host "Sugerido:" -ForegroundColor Yellow
    Write-Host "  $($FirstLine.TrimEnd('.'))"
    exit 1
}

# ============================================================
# Validación final OK
# ============================================================

Write-Host "Commit message válido." -ForegroundColor Green
Write-Host "Tipo: $CommitType"

if (![string]::IsNullOrWhiteSpace($Scope)) {
    Write-Host "Scope: $Scope"
}

exit 0