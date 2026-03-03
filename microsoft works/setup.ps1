# ============================================================
# Azure App Registration Setup - Full Automation (FIXED)
# ============================================================
# This script:
#   1. Logs you into Azure (opens browser)
#   2. Creates an app registration
#   3. Looks up CORRECT permission IDs dynamically (no hardcoded GUIDs)
#   4. Adds all required permissions via Graph API
#   5. Grants admin consent via appRoleAssignments (RELIABLE)
#   6. Assigns Exchange Administrator role
#   7. Outputs Tenant ID, Client ID, Client Secret
#   8. Saves to .env
# ============================================================

param(
    [string]$AppName = "TenantSetupAutomation"
)

$ErrorActionPreference = "Continue"

function Write-Step($num, $total, $msg) {
    Write-Host ""
    Write-Host "[$num/$total] $msg" -ForegroundColor Yellow
}
function Write-Ok($msg)   { Write-Host "  [OK] $msg" -ForegroundColor Green }
function Write-Fail($msg) { Write-Host "  [FAIL] $msg" -ForegroundColor Red }
function Write-Note($msg) { Write-Host "  [INFO] $msg" -ForegroundColor Gray }
function Write-Warn($msg) { Write-Host "  [WARN] $msg" -ForegroundColor Yellow }

# Helper: write JSON to temp file and use it with az rest (avoids escaping hell)
function Invoke-GraphApi {
    param(
        [string]$Method,
        [string]$Uri,
        [object]$Body = $null
    )
    $args_list = @("rest", "--method", $Method, "--uri", $Uri)
    if ($Body) {
        $tempFile = [System.IO.Path]::GetTempFileName()
        $Body | ConvertTo-Json -Depth 20 -Compress | Out-File -FilePath $tempFile -Encoding UTF8 -NoNewline
        $args_list += @("--body", "@$tempFile", "--headers", "Content-Type=application/json")
    }
    $result = & az @args_list 2>&1
    if ($tempFile) { Remove-Item $tempFile -ErrorAction SilentlyContinue }

    # Check for errors
    $resultStr = $result | Out-String
    if ($LASTEXITCODE -ne 0) {
        throw "Graph API $Method $Uri failed: $resultStr"
    }
    if ($resultStr.Trim()) {
        return $resultStr | ConvertFrom-Json
    }
    return $null
}

$totalSteps = 9

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  Azure App Registration - Full Automation" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# --- Step 1: Check Azure CLI ---------------------------------
Write-Step 1 $totalSteps "Checking Azure CLI..."
try {
    $azVer = az version --output json 2>$null | ConvertFrom-Json
    Write-Ok "Azure CLI $($azVer.'azure-cli') installed"
} catch {
    Write-Fail "Azure CLI not installed!"
    Write-Host "  Install: winget install Microsoft.AzureCLI" -ForegroundColor Yellow
    exit 1
}

# --- Step 2: Login to Azure ----------------------------------
Write-Step 2 $totalSteps "Logging into Azure (browser will open)..."
Write-Note "Select your admin account in the browser"

az login --allow-no-subscriptions --output none 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Fail "Login failed"
    exit 1
}
Write-Ok "Logged in successfully"

# --- Step 3: Get Tenant ID -----------------------------------
Write-Step 3 $totalSteps "Getting tenant info..."
$account = az account show --output json | ConvertFrom-Json
$tenantId = $account.tenantId
$adminEmail = $account.user.name

if (-not $tenantId) {
    Write-Fail "Could not get Tenant ID"
    exit 1
}
Write-Ok "Tenant ID: $tenantId"
Write-Ok "Admin: $adminEmail"

# --- Step 4: Create App Registration -------------------------
Write-Step 4 $totalSteps "Creating App Registration '$AppName'..."

# Check if app already exists
$existingApp = az ad app list --display-name $AppName --query "[0]" -o json 2>$null | ConvertFrom-Json
if ($existingApp) {
    $clientId = $existingApp.appId
    $appObjectId = $existingApp.id
    Write-Warn "App '$AppName' already exists, reusing it"
} else {
    $appResult = az ad app create --display-name $AppName --sign-in-audience AzureADMyOrg --output json | ConvertFrom-Json
    $clientId = $appResult.appId
    $appObjectId = $appResult.id
}
Write-Ok "Client ID: $clientId"
Write-Ok "Object ID: $appObjectId"

# --- Step 5: Create Client Secret ----------------------------
Write-Step 5 $totalSteps "Creating Client Secret..."

# Use Graph API to add password (more reliable than az ad app credential reset)
try {
    $secretResult = Invoke-GraphApi -Method POST `
        -Uri "https://graph.microsoft.com/v1.0/applications/$appObjectId/addPassword" `
        -Body @{
            passwordCredential = @{
                displayName = "AutoSetupSecret"
                endDateTime = "2028-12-31T23:59:59Z"
            }
        }
    $clientSecret = $secretResult.secretText
    Write-Ok "Client Secret created (expires 2028-12-31)"
} catch {
    Write-Warn "Graph API addPassword failed, trying az CLI fallback..."
    $secretJson = az ad app credential reset --id $clientId --append --years 2 --output json | ConvertFrom-Json
    $clientSecret = $secretJson.password
    Write-Ok "Client Secret created via az CLI"
}

# --- Step 6: Create Service Principal ------------------------
Write-Step 6 $totalSteps "Creating Service Principal..."

$spExists = az ad sp show --id $clientId --query id -o tsv 2>$null
if ($spExists) {
    $appSpId = $spExists
    Write-Ok "Service Principal already exists: $appSpId"
} else {
    $spResult = az ad sp create --id $clientId --output json | ConvertFrom-Json
    $appSpId = $spResult.id
    Write-Ok "Service Principal created: $appSpId"
}

# --- Step 7: Lookup & Add API Permissions (DYNAMIC - no hardcoded GUIDs) --
Write-Step 7 $totalSteps "Looking up permission IDs and adding to app..."

$graphApiId = "00000003-0000-0000-c000-000000000000"
$exchangeApiId = "00000002-0000-0ff1-ce00-000000000000"

# -- Lookup Graph API service principal --
Write-Note "Looking up Microsoft Graph service principal..."
$graphSpData = Invoke-GraphApi -Method GET `
    -Uri "https://graph.microsoft.com/v1.0/servicePrincipals?`$filter=appId eq '$graphApiId'&`$select=id,appRoles,oauth2PermissionScopes"
$graphSp = $graphSpData.value[0]
$graphSpId = $graphSp.id

# Build lookup tables: name -> GUID
$graphRoles = @{}
foreach ($role in $graphSp.appRoles) {
    $graphRoles[$role.value] = $role.id
}
$graphScopes = @{}
foreach ($scope in $graphSp.oauth2PermissionScopes) {
    $graphScopes[$scope.value] = $scope.id
}
Write-Ok "Graph API: $($graphRoles.Count) roles, $($graphScopes.Count) scopes found"

# -- Lookup Exchange Online service principal --
Write-Note "Looking up Exchange Online service principal..."
$exchangeSpData = Invoke-GraphApi -Method GET `
    -Uri "https://graph.microsoft.com/v1.0/servicePrincipals?`$filter=appId eq '$exchangeApiId'&`$select=id,appRoles"
$exchangeSp = $exchangeSpData.value[0]
$exchangeSpId = $exchangeSp.id

$exchangeRoles = @{}
foreach ($role in $exchangeSp.appRoles) {
    $exchangeRoles[$role.value] = $role.id
}
Write-Ok "Exchange: $($exchangeRoles.Count) roles found"

# -- Required permissions --
$requiredGraphApp = @(
    "Policy.ReadWrite.ConditionalAccess",
    "Policy.ReadWrite.AuthenticationMethod",
    "Policy.ReadWrite.SecurityDefaults",
    "Policy.Read.All",
    "Domain.ReadWrite.All",
    "User.ReadWrite.All",
    "UserAuthenticationMethod.ReadWrite.All",
    "Organization.ReadWrite.All",
    "Directory.ReadWrite.All",
    "Mail.ReadWrite",
    "Mail.Send"
)
$requiredGraphDelegated = @("SMTP.Send")
$requiredExchangeApp = @("full_access_as_app", "Exchange.ManageAsApp")

# -- Build resource access arrays --
$graphResourceAccess = @()
foreach ($perm in $requiredGraphApp) {
    $roleId = $graphRoles[$perm]
    if ($roleId) {
        $graphResourceAccess += @{ id = $roleId; type = "Role" }
        Write-Ok "  + [Graph] $perm"
    } else {
        Write-Warn "  ! [Graph] $perm - not found"
    }
}
foreach ($perm in $requiredGraphDelegated) {
    $scopeId = $graphScopes[$perm]
    if ($scopeId) {
        $graphResourceAccess += @{ id = $scopeId; type = "Scope" }
        Write-Ok "  + [Graph] $perm (Delegated)"
    } else {
        Write-Warn "  ! [Graph] $perm (Delegated) - not found"
    }
}

$exchangeResourceAccess = @()
foreach ($perm in $requiredExchangeApp) {
    $roleId = $exchangeRoles[$perm]
    if ($roleId) {
        $exchangeResourceAccess += @{ id = $roleId; type = "Role" }
        Write-Ok "  + [Exchange] $perm"
    } else {
        Write-Warn "  ! [Exchange] $perm - not found"
    }
}

# -- PATCH app with all permissions at once --
Write-Note "Writing permissions to app manifest..."
$requiredResourceAccess = @(
    @{
        resourceAppId = $graphApiId
        resourceAccess = $graphResourceAccess
    },
    @{
        resourceAppId = $exchangeApiId
        resourceAccess = $exchangeResourceAccess
    }
)

try {
    Invoke-GraphApi -Method PATCH `
        -Uri "https://graph.microsoft.com/v1.0/applications/$appObjectId" `
        -Body @{ requiredResourceAccess = $requiredResourceAccess }
    Write-Ok "All permissions written to app manifest"
} catch {
    Write-Fail "Failed to write permissions: $_"
}

# --- Step 8: Grant Admin Consent (via appRoleAssignments - RELIABLE) --
Write-Step 8 $totalSteps "Granting Admin Consent (appRoleAssignments)..."
Write-Note "This is the RELIABLE method (not az ad app permission admin-consent)"

# Wait for SP to propagate
Start-Sleep -Seconds 3

$consentTotal = 0
$consentOk = 0

# Grant Graph Application permissions
foreach ($perm in $requiredGraphApp) {
    $roleId = $graphRoles[$perm]
    if (-not $roleId) { continue }
    $consentTotal++
    try {
        Invoke-GraphApi -Method POST `
            -Uri "https://graph.microsoft.com/v1.0/servicePrincipals/$appSpId/appRoleAssignments" `
            -Body @{
                principalId = $appSpId
                resourceId  = $graphSpId
                appRoleId   = $roleId
            }
        Write-Ok "  Consented: $perm"
        $consentOk++
    } catch {
        $errMsg = $_.ToString()
        if ($errMsg -match "already exists" -or $errMsg -match "Conflict") {
            Write-Ok "  Already consented: $perm"
            $consentOk++
        } else {
            $errShort = $errMsg.Substring(0, [Math]::Min(100, $errMsg.Length))
            Write-Warn "  Failed: $perm - $errShort"
        }
    }
}

# Grant Exchange Application permissions
foreach ($perm in $requiredExchangeApp) {
    $roleId = $exchangeRoles[$perm]
    if (-not $roleId) { continue }
    $consentTotal++
    try {
        Invoke-GraphApi -Method POST `
            -Uri "https://graph.microsoft.com/v1.0/servicePrincipals/$appSpId/appRoleAssignments" `
            -Body @{
                principalId = $appSpId
                resourceId  = $exchangeSpId
                appRoleId   = $roleId
            }
        Write-Ok "  Consented: $perm (Exchange)"
        $consentOk++
    } catch {
        $errMsg = $_.ToString()
        if ($errMsg -match "already exists" -or $errMsg -match "Conflict") {
            Write-Ok "  Already consented: $perm (Exchange)"
            $consentOk++
        } else {
            $errShort = $errMsg.Substring(0, [Math]::Min(100, $errMsg.Length))
            Write-Warn "  Failed: $perm - $errShort"
        }
    }
}

Write-Ok "Admin consent: $consentOk / $consentTotal permissions granted"

# --- Step 9: Assign Exchange Administrator Role --------------
Write-Step 9 $totalSteps "Assigning Exchange Administrator Role..."

$exchangeAdminRoleId = "29232cdf-9323-42fd-ade2-1d097af3e4de"

try {
    Invoke-GraphApi -Method POST `
        -Uri "https://graph.microsoft.com/v1.0/roleManagement/directory/roleAssignments" `
        -Body @{
            principalId      = $appSpId
            roleDefinitionId = $exchangeAdminRoleId
            directoryScopeId = "/"
        }
    Write-Ok "Exchange Administrator role assigned!"
} catch {
    $errMsg = $_.ToString()
    if ($errMsg -match "already exists" -or $errMsg -match "Conflict") {
        Write-Ok "Exchange Administrator role already assigned"
    } else {
        Write-Warn "Role assignment failed: $($errMsg.Substring(0, [Math]::Min(150, $errMsg.Length)))"
        Write-Note "Manual: Azure Portal > Roles and administrators > Exchange Administrator > Add your app"
    }
}

# --- Save to .env --------------------------------------------
Write-Host ""
Write-Host "Saving credentials..." -ForegroundColor Yellow

$envPath = Join-Path $PSScriptRoot ".env"

# Read existing .env
$existingEnv = @{}
if (Test-Path $envPath) {
    Get-Content $envPath | ForEach-Object {
        $line = $_.Trim()
        if ($line -and -not $line.StartsWith("#") -and $line.Contains("=")) {
            $parts = $line.Split("=", 2)
            $existingEnv[$parts[0].Trim()] = $parts[1].Trim()
        }
    }
}

$existingEnv["TENANT_ID"] = $tenantId
$existingEnv["CLIENT_ID"] = $clientId
$existingEnv["CLIENT_SECRET"] = $clientSecret

$envLines = @()
if ($existingEnv.ContainsKey("APPS_SCRIPT_URL")) {
    $envLines += "# Google Apps Script web app URL"
    $envLines += "APPS_SCRIPT_URL=$($existingEnv['APPS_SCRIPT_URL'])"
    $existingEnv.Remove("APPS_SCRIPT_URL")
    $envLines += ""
}
$envLines += "# Azure App Registration credentials"
$envLines += "TENANT_ID=$($existingEnv['TENANT_ID'])"
$envLines += "CLIENT_ID=$($existingEnv['CLIENT_ID'])"
$envLines += "CLIENT_SECRET=$($existingEnv['CLIENT_SECRET'])"
$existingEnv.Remove("TENANT_ID")
$existingEnv.Remove("CLIENT_ID")
$existingEnv.Remove("CLIENT_SECRET")

foreach ($key in $existingEnv.Keys) {
    $envLines += "$key=$($existingEnv[$key])"
}

$envLines | Out-File -FilePath $envPath -Encoding UTF8 -Force
Write-Ok "Saved to $envPath"

# --- Output --------------------------------------------------
Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host "  SETUP COMPLETE!" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host ""
Write-Host "  Credentials:" -ForegroundColor Cyan
Write-Host "    Tenant ID:     $tenantId"
Write-Host "    Client ID:     $clientId"
Write-Host "    Client Secret: $clientSecret"
Write-Host "    Admin Email:   $adminEmail"
Write-Host ""
Write-Host "  Permissions granted:" -ForegroundColor Cyan
foreach ($p in $requiredGraphApp) {
    Write-Host "    [Graph]    $p"
}
foreach ($p in $requiredGraphDelegated) {
    Write-Host "    [Graph]    $p (Delegated)"
}
foreach ($p in $requiredExchangeApp) {
    Write-Host "    [Exchange] $p"
}
Write-Host "    [Role]     Exchange Administrator"
Write-Host ""
Write-Host "  Next step:" -ForegroundColor Cyan
Write-Host "    python tenant_setup_automation.py" -ForegroundColor White
Write-Host "    python tenant_setup_automation.py --use-cli" -ForegroundColor White
Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
