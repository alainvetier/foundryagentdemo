// Whisker Works demo environment
// Foundry (account + project + 2 model deployments), API Management (Basic v2 AI gateway),
// App Service (cat store API + storefront, A2A agent), Log Analytics + Application Insights.
targetScope = 'resourceGroup'

@description('Azure region for the demo resources. Confirm model availability and quota in this region.')
param location string = 'southeastasia'

@description('Tags copied from the demo resource group onto resources that support tags.')
param resourceTags object = resourceGroup().tags ?? {}

@description('Short prefix used for resource names.')
@maxLength(8)
param prefix string = 'whisker'

@description('APIM publisher email.')
param publisherEmail string

@description('APIM publisher name.')
param publisherName string = 'Whisker Works Inc.'

@description('Object ID of the user running the demo (gets Azure AI User on the Foundry account).')
param deployerPrincipalId string = ''

@description('Model used by the agents on day one.')
param chatModelName string = 'gpt-4.1-mini'
param chatModelVersion string = '2025-04-14'

@description('Model used for the "update the agent to a new model" demo.')
param newModelName string = 'gpt-5-mini'
param newModelVersion string = '2025-08-07'

@description('Capacity (thousands of TPM) for the initial chat model deployment.')
param modelCapacity int = 50

@description('Capacity (thousands of TPM) for the upgraded model, shared by agent model calls including Code Interpreter follow-ups.')
param newModelCapacity int = 200

var suffix = take(uniqueString(resourceGroup().id), 6)
var foundryName = '${prefix}-ai-${suffix}'
var projectName = 'whisker-works'
var apimName = '${prefix}-apim-${suffix}'
var planName = '${prefix}-plan-${suffix}'
var catstoreAppName = '${prefix}-store-${suffix}'
var a2aAppName = '${prefix}-a2a-${suffix}'
var foundryHost = 'https://${foundryName}.cognitiveservices.azure.com'
var projectEndpoint = 'https://${foundryName}.services.ai.azure.com/api/projects/${projectName}'

// Built-in role definition IDs
var roleAzureAIUser = '53ca6127-db72-4b80-b1b0-d745d6d5456d'
var roleFoundryProjectManager = 'eadc314b-1a2d-4efa-be10-5d325db5065e'
var roleCognitiveServicesOpenAIUser = '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd'
var roleCognitiveServicesUser = 'a97b65f3-24c7-4388-baec-2e87135dc908'

// ---------------------------------------------------------------------------
// Monitoring
// ---------------------------------------------------------------------------
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
    // Required so APIM token metrics keep their dimensions
    #disable-next-line BCP037
    CustomMetricsOptedInType: 'WithDimensions'
  }
}

// ---------------------------------------------------------------------------
// Microsoft Foundry
// ---------------------------------------------------------------------------
resource foundry 'Microsoft.CognitiveServices/accounts@2025-06-01' = {
  name: foundryName
  tags: resourceTags
  location: location
  kind: 'AIServices'
  sku: { name: 'S0' }
  identity: { type: 'SystemAssigned' }
  properties: {
    allowProjectManagement: true
    customSubDomainName: foundryName
    publicNetworkAccess: 'Enabled'
    disableLocalAuth: false
  }
}

resource project 'Microsoft.CognitiveServices/accounts/projects@2025-06-01' = {
  parent: foundry
  name: projectName
  tags: resourceTags
  location: location
  identity: { type: 'SystemAssigned' }
  properties: {
    displayName: 'Whisker Works'
    description: 'Agents for Whisker Works, the retail store run by techie cats.'
  }
  dependsOn: [ newDeployment ]
}

module foundryAppInsightsConnection 'modules/foundry-appinsights-connection.bicep' = {
  name: 'whisker-foundry-appinsights'
  params: {
    foundryAccountName: foundry.name
    projectName: project.name
    appInsightsName: appInsights.name
    appInsightsResourceGroup: resourceGroup().name
    appInsightsConnectionString: appInsights.properties.ConnectionString
  }
}

module appInsightsProjectReader 'modules/appinsights-project-reader.bicep' = {
  name: 'whisker-appinsights-project-reader'
  params: {
    appInsightsName: appInsights.name
    projectPrincipalId: project.identity.principalId
    projectResourceId: project.id
  }
}

resource chatDeployment 'Microsoft.CognitiveServices/accounts/deployments@2025-06-01' = {
  parent: foundry
  name: chatModelName
  sku: { name: 'GlobalStandard', capacity: modelCapacity }
  properties: {
    model: { format: 'OpenAI', name: chatModelName, version: chatModelVersion }
  }
}

resource newDeployment 'Microsoft.CognitiveServices/accounts/deployments@2025-06-01' = {
  parent: foundry
  name: newModelName
  sku: { name: 'GlobalStandard', capacity: newModelCapacity }
  properties: {
    model: { format: 'OpenAI', name: newModelName, version: newModelVersion }
  }
  dependsOn: [ chatDeployment ]
}

// ---------------------------------------------------------------------------
// App Service: cat store API + storefront, and the A2A agent
// ---------------------------------------------------------------------------
resource plan 'Microsoft.Web/serverfarms@2024-04-01' = {
  name: planName
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

// ---------------------------------------------------------------------------
// API Management (AI gateway)
// ---------------------------------------------------------------------------
resource apim 'Microsoft.ApiManagement/service@2024-06-01-preview' = {
  name: apimName
  tags: resourceTags
  location: location
  sku: { name: 'BasicV2', capacity: 1 }
  identity: { type: 'SystemAssigned' }
  properties: {
    publisherEmail: publisherEmail
    publisherName: publisherName
  }
}

resource apimLogger 'Microsoft.ApiManagement/service/loggers@2024-06-01-preview' = {
  parent: apim
  name: 'whisker-appinsights-logger'
  properties: {
    loggerType: 'applicationInsights'
    credentials: { instrumentationKey: appInsights.properties.InstrumentationKey }
    isBuffered: true
    resourceId: appInsights.id
  }
}

// Body bytes = 0 at global scope is required for MCP streaming to work.
resource apimDiagnostics 'Microsoft.ApiManagement/service/diagnostics@2024-06-01-preview' = {
  parent: apim
  name: 'applicationinsights'
  properties: {
    loggerId: apimLogger.id
    alwaysLog: 'allErrors'
    metrics: true
    verbosity: 'information'
    sampling: { samplingType: 'fixed', percentage: 100 }
    frontend: {
      request: { body: { bytes: 0 } }
      response: { body: { bytes: 0 } }
    }
    backend: {
      request: { body: { bytes: 0 } }
      response: { body: { bytes: 0 } }
    }
  }
}

resource modelsBackend 'Microsoft.ApiManagement/service/backends@2024-06-01-preview' = {
  parent: apim
  name: 'whisker-foundry-models'
  properties: {
    description: 'Foundry model endpoint (Azure OpenAI compatible)'
    url: foundryHost
    protocol: 'http'
    circuitBreaker: {
      rules: [
        {
          name: 'models-breaker'
          failureCondition: {
            count: 3
            interval: 'PT1M'
            statusCodeRanges: [ { min: 429, max: 429 }, { min: 500, max: 599 } ]
          }
          tripDuration: 'PT1M'
          acceptRetryAfter: true
        }
      ]
    }
  }
}

// Foundry accounts expose Azure AI Content Safety on the same host.
resource contentSafetyBackend 'Microsoft.ApiManagement/service/backends@2024-06-01-preview' = {
  parent: apim
  name: 'whisker-content-safety'
  properties: {
    description: 'Azure AI Content Safety (Foundry account)'
    url: foundryHost
    protocol: 'http'
    credentials: {
      // Supported by the service; missing from published type definitions
      #disable-next-line BCP037
      managedIdentity: { resource: 'https://cognitiveservices.azure.com' }
    }
  }
}

// --- Layer 1: Models --------------------------------------------------------
resource modelsApi 'Microsoft.ApiManagement/service/apis@2024-06-01-preview' = {
  parent: apim
  name: 'foundry-models'
  properties: {
    displayName: 'Foundry Models (AI Gateway)'
    description: 'Governed access to Foundry model deployments (Azure OpenAI compatible).'
    path: 'models'
    protocols: [ 'https' ]
    serviceUrl: foundryHost
    subscriptionRequired: true
    subscriptionKeyParameterNames: { header: 'api-key', query: 'api-key' }
  }
}

resource modelsPost 'Microsoft.ApiManagement/service/apis/operations@2024-06-01-preview' = {
  parent: modelsApi
  name: 'post-all'
  properties: { displayName: 'POST /*', method: 'POST', urlTemplate: '/*' }
}

resource modelsGet 'Microsoft.ApiManagement/service/apis/operations@2024-06-01-preview' = {
  parent: modelsApi
  name: 'get-all'
  properties: { displayName: 'GET /*', method: 'GET', urlTemplate: '/*' }
}

resource modelsPolicy 'Microsoft.ApiManagement/service/apis/policies@2024-06-01-preview' = {
  parent: modelsApi
  name: 'policy'
  properties: {
    format: 'rawxml'
    value: loadTextContent('../apim/policies/models-api-policy.xml')
  }
  dependsOn: [ modelsBackend, contentSafetyBackend ]
}

// --- REST API that will be turned into an MCP server (Layer 2: Tools) -------
resource storeApi 'Microsoft.ApiManagement/service/apis@2024-06-01-preview' = {
  parent: apim
  name: 'whisker-works-api'
  properties: {
    displayName: 'Whisker Works Store API'
    description: 'Products, inventory, orders and cat facts for the Whisker Works store.'
    path: 'store'
    protocols: [ 'https' ]
    format: 'openapi+json'
    value: loadTextContent('../src/catstore-api/openapi.json')
    serviceUrl: 'https://${catstoreApp.properties.defaultHostName}/api'
    subscriptionRequired: true
  }
}

// --- Products & subscriptions ------------------------------------------------
resource bronze 'Microsoft.ApiManagement/service/products@2024-06-01-preview' = {
  parent: apim
  name: 'whisker-bronze'
  properties: {
    displayName: 'Whisker Bronze (Kitten tier)'
    description: 'Low token budget, read-only friendly. For interns and prototypes.'
    subscriptionRequired: true
    approvalRequired: false
    state: 'published'
  }
}

resource gold 'Microsoft.ApiManagement/service/products@2024-06-01-preview' = {
  parent: apim
  name: 'whisker-gold'
  properties: {
    displayName: 'Whisker Gold (Top Cat tier)'
    description: 'High token budget. For production agents.'
    subscriptionRequired: true
    approvalRequired: false
    state: 'published'
  }
}

resource bronzeModels 'Microsoft.ApiManagement/service/products/apis@2024-06-01-preview' = {
  parent: bronze
  name: modelsApi.name
}
resource goldModels 'Microsoft.ApiManagement/service/products/apis@2024-06-01-preview' = {
  parent: gold
  name: modelsApi.name
}
resource bronzeStore 'Microsoft.ApiManagement/service/products/apis@2024-06-01-preview' = {
  parent: bronze
  name: storeApi.name
}
resource goldStore 'Microsoft.ApiManagement/service/products/apis@2024-06-01-preview' = {
  parent: gold
  name: storeApi.name
}

resource subBronze 'Microsoft.ApiManagement/service/subscriptions@2024-06-01-preview' = {
  parent: apim
  name: 'whisker-demo-bronze'
  properties: { displayName: 'Demo - Bronze', scope: bronze.id, state: 'active' }
}

resource subGold 'Microsoft.ApiManagement/service/subscriptions@2024-06-01-preview' = {
  parent: apim
  name: 'whisker-demo-gold'
  properties: { displayName: 'Demo - Gold', scope: gold.id, state: 'active' }
}

// Used by the A2A agent to call models through the gateway (agents are governed like any app).
resource subA2A 'Microsoft.ApiManagement/service/subscriptions@2024-06-01-preview' = {
  parent: apim
  name: 'whisker-a2a-agent-internal'
  properties: { displayName: 'A2A agent (internal)', scope: gold.id, state: 'active' }
}

// ---------------------------------------------------------------------------
// A2A agent web app (needs APIM to exist first)
// ---------------------------------------------------------------------------
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
        { name: 'APIM_MODELS_ENDPOINT', value: '${apim.properties.gatewayUrl}/models' }
        { name: 'APIM_MODELS_KEY', value: subA2A.listSecrets().primaryKey }
        { name: 'CHAT_MODEL', value: chatModelName }
      ]
    }
  }
}

// ---------------------------------------------------------------------------
// Role assignments
// ---------------------------------------------------------------------------
resource apimOpenAIUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: foundry
  name: guid(foundry.id, apim.id, roleCognitiveServicesOpenAIUser)
  properties: {
    principalId: apim.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleCognitiveServicesOpenAIUser)
  }
}

resource apimCognitiveUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: foundry
  name: guid(foundry.id, apim.id, roleCognitiveServicesUser)
  properties: {
    principalId: apim.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleCognitiveServicesUser)
  }
}

resource storefrontAIUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: foundry
  name: guid(foundry.id, catstoreApp.id, roleAzureAIUser)
  properties: {
    principalId: catstoreApp.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleAzureAIUser)
  }
}

resource deployerAIUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(deployerPrincipalId)) {
  scope: foundry
  name: guid(foundry.id, deployerPrincipalId, roleAzureAIUser)
  properties: {
    principalId: deployerPrincipalId
    principalType: 'User'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleAzureAIUser)
  }
}

// Required to deploy hosted agents (docs/11)
resource deployerProjectManager 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(deployerPrincipalId)) {
  scope: project
  name: guid(project.id, deployerPrincipalId, roleFoundryProjectManager)
  properties: {
    principalId: deployerPrincipalId
    principalType: 'User'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleFoundryProjectManager)
  }
}

// ---------------------------------------------------------------------------
// Outputs
// ---------------------------------------------------------------------------
output resourceGroup string = resourceGroup().name
output foundryName string = foundry.name
output projectName string = project.name
output projectEndpoint string = projectEndpoint
output chatModel string = chatDeployment.name
output newModel string = newDeployment.name
output apimName string = apim.name
output apimResourceGroup string = resourceGroup().name
output apimGatewayUrl string = apim.properties.gatewayUrl
output catstoreAppName string = catstoreApp.name
output catstoreUrl string = 'https://${catstoreApp.properties.defaultHostName}'
output a2aAppName string = a2aApp.name
output a2aUrl string = 'https://${a2aApp.properties.defaultHostName}'
output appInsightsName string = appInsights.name
