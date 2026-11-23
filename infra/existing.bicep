// Whisker Works demo on EXISTING Foundry + EXISTING API Management (see docs/00b-setup-existing-environment.md).
// Deploys into a (new) demo resource group: App Insights, App Service plan + 2 web apps.
// Configures the existing APIM and Foundry through cross-resource-group modules.
targetScope = 'resourceGroup'

@description('Azure region for the demo web apps and monitoring resources; Foundry and APIM remain where they already exist.')
param location string = 'southeastasia'

@description('Tags copied from the demo resource group onto resources that support tags.')
param resourceTags object = resourceGroup().tags ?? {}
@maxLength(8)
param prefix string = 'whisker'

@description('Existing Foundry (AIServices) account name and its resource group.')
param foundryAccountName string
param foundryResourceGroup string
@description('Existing Foundry project name (new Foundry project under the account, not a hub project).')
param projectName string

@description('Existing API Management instance and its resource group. Must have a system-assigned managed identity.')
param apimName string
param apimResourceGroup string

@description('false = reuse existing deployments named chatModelName / newModelName.')
param createModelDeployments bool = true
param chatModelName string = 'gpt-4.1-mini'
param chatModelVersion string = '2025-04-14'
param newModelName string = 'gpt-5-mini'
param newModelVersion string = '2025-08-07'
@description('Capacity (thousands of TPM) for the initial chat model deployment.')
param modelCapacity int = 50
@description('Capacity (thousands of TPM) for the upgraded model, shared by agent model calls including Code Interpreter follow-ups.')
param newModelCapacity int = 200

@description('Leave false on shared APIM instances (uses API-scoped diagnostics instead of the All APIs one).')
param configureGlobalApimDiagnostics bool = false
@description('Connect the new demo Application Insights resource to the existing Foundry project. Set false to preserve a project connection that already exists.')
param connectFoundryAppInsights bool = true
@description('Change if these paths are already used in your APIM instance.')
param modelsApiPath string = 'models'
param storeApiPath string = 'store'

param deployerPrincipalId string = ''

var suffix = take(uniqueString(resourceGroup().id), 6)
var catstoreAppName = '${prefix}-store-${suffix}'
var a2aAppName = '${prefix}-a2a-${suffix}'

resource foundry 'Microsoft.CognitiveServices/accounts@2025-06-01' existing = {
  name: foundryAccountName
  scope: resourceGroup(foundryResourceGroup)
}

resource apim 'Microsoft.ApiManagement/service@2024-06-01-preview' existing = {
  name: apimName
  scope: resourceGroup(apimResourceGroup)
}

resource subA2A 'Microsoft.ApiManagement/service/subscriptions@2024-06-01-preview' existing = {
  parent: apim
  name: 'whisker-a2a-agent-internal'
}

var subdomain = foundry.properties.customSubDomainName
var foundryHost = 'https://${subdomain}.cognitiveservices.azure.com'
var projectEndpoint = 'https://${subdomain}.services.ai.azure.com/api/projects/${projectName}'

// --- Monitoring ---------------------------------------------------------------
resource law 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: '${prefix}-law-${suffix}'
  tags: resourceTags
  location: location
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
  }
}

resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: '${prefix}-appi-${suffix}'
  tags: resourceTags
  location: location
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: law.id
    #disable-next-line BCP037
    CustomMetricsOptedInType: 'WithDimensions'
  }
}

// --- Web apps -----------------------------------------------------------------
resource plan 'Microsoft.Web/serverfarms@2024-04-01' = {
  name: '${prefix}-plan-${suffix}'
  tags: resourceTags
  location: location
  kind: 'linux'
  sku: { name: 'B1' }
  properties: { reserved: true }
}

resource catstoreApp 'Microsoft.Web/sites@2024-04-01' = {
  name: catstoreAppName
  tags: resourceTags
  location: location
  kind: 'app,linux'
  identity: { type: 'SystemAssigned' }
  properties: {
    serverFarmId: plan.id
    httpsOnly: true
    siteConfig: {
      linuxFxVersion: 'PYTHON|3.12'
      appCommandLine: 'python -m uvicorn main:app --host 0.0.0.0 --port 8000'
      ftpsState: 'Disabled'
      minTlsVersion: '1.2'
      appSettings: [
        { name: 'SCM_DO_BUILD_DURING_DEPLOYMENT', value: 'true' }
        { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: appInsights.properties.ConnectionString }
        { name: 'FOUNDRY_PROJECT_ENDPOINT', value: projectEndpoint }
        { name: 'STOREFRONT_AGENT_NAME', value: 'whiskers-concierge-pro' }
      ]
    }
  }
}

// --- Existing APIM: APIs, backends, products, policies -----------------------
module apimConfig 'modules/apim-demo-config.bicep' = {
  name: 'whisker-apim-config'
  scope: resourceGroup(apimResourceGroup)
  params: {
    apimName: apimName
    foundryHost: foundryHost
    catstoreHostName: catstoreApp.properties.defaultHostName
    appInsightsId: appInsights.id
    appInsightsInstrumentationKey: appInsights.properties.InstrumentationKey
    configureGlobalDiagnostics: configureGlobalApimDiagnostics
    modelsApiPath: modelsApiPath
    storeApiPath: storeApiPath
  }
}

// --- Existing Foundry: model deployments + RBAC ------------------------------
module foundryAccess 'modules/foundry-demo-access.bicep' = {
  name: 'whisker-foundry-access'
  scope: resourceGroup(foundryResourceGroup)
  params: {
    foundryAccountName: foundryAccountName
    projectName: projectName
    createModelDeployments: createModelDeployments
    chatModelName: chatModelName
    chatModelVersion: chatModelVersion
    newModelName: newModelName
    newModelVersion: newModelVersion
    modelCapacity: modelCapacity
    newModelCapacity: newModelCapacity
    apimPrincipalId: apim.identity.principalId
    storefrontPrincipalId: catstoreApp.identity.principalId
    deployerPrincipalId: deployerPrincipalId
  }
}

module foundryAppInsightsConnection 'modules/foundry-appinsights-connection.bicep' = if (connectFoundryAppInsights) {
  name: 'whisker-foundry-appinsights'
  scope: resourceGroup(foundryResourceGroup)
  params: {
    foundryAccountName: foundryAccountName
    projectName: projectName
    appInsightsName: appInsights.name
    appInsightsResourceGroup: resourceGroup().name
    appInsightsConnectionString: appInsights.properties.ConnectionString
  }
  dependsOn: [ foundryAccess ]
}

module appInsightsProjectReader 'modules/appinsights-project-reader.bicep' = if (connectFoundryAppInsights) {
  name: 'whisker-appinsights-project-reader'
  params: {
    appInsightsName: appInsights.name
    projectPrincipalId: foundryAccess.outputs.projectPrincipalId
    projectResourceId: foundryAccess.outputs.projectResourceId
  }
}

resource a2aApp 'Microsoft.Web/sites@2024-04-01' = {
  name: a2aAppName
  tags: resourceTags
  location: location
  kind: 'app,linux'
  identity: { type: 'SystemAssigned' }
  properties: {
    serverFarmId: plan.id
    httpsOnly: true
    siteConfig: {
      linuxFxVersion: 'PYTHON|3.12'
      appCommandLine: 'python -m uvicorn main:app --host 0.0.0.0 --port 8000'
      ftpsState: 'Disabled'
      minTlsVersion: '1.2'
      appSettings: [
        { name: 'SCM_DO_BUILD_DURING_DEPLOYMENT', value: 'true' }
        { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: appInsights.properties.ConnectionString }
        { name: 'A2A_PUBLIC_URL', value: 'https://${a2aAppName}.azurewebsites.net' }
        { name: 'APIM_MODELS_ENDPOINT', value: '${apim.properties.gatewayUrl}/${modelsApiPath}' }
        { name: 'APIM_MODELS_KEY', value: subA2A.listSecrets().primaryKey }
        { name: 'CHAT_MODEL', value: chatModelName }
      ]
    }
  }
  dependsOn: [ apimConfig ]
}

// Same output names as main.bicep so scripts/deploy.sh works for both modes.
output resourceGroup string = resourceGroup().name
output foundryName string = foundry.name
output projectName string = projectName
output projectEndpoint string = projectEndpoint
output chatModel string = chatModelName
output newModel string = newModelName
output apimName string = apim.name
output apimResourceGroup string = apimResourceGroup
output apimGatewayUrl string = apim.properties.gatewayUrl
output catstoreAppName string = catstoreApp.name
output catstoreUrl string = 'https://${catstoreApp.properties.defaultHostName}'
output a2aAppName string = a2aApp.name
output a2aUrl string = 'https://${a2aApp.properties.defaultHostName}'
output appInsightsName string = appInsights.name
