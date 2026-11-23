// Configures an EXISTING API Management instance for the Whisker Works demo (deployed at the APIM resource group scope).
// Everything is additive and name-prefixed so it can live next to other APIs in a shared instance.
targetScope = 'resourceGroup'

param apimName string
@description('Foundry account host, e.g. https://<subdomain>.cognitiveservices.azure.com')
param foundryHost string
param catstoreHostName string
param appInsightsId string
param appInsightsInstrumentationKey string
@description('true = set the GLOBAL (All APIs) App Insights diagnostic. false = API-scoped diagnostics only (safer on shared instances).')
param configureGlobalDiagnostics bool = false
param modelsApiPath string = 'models'
param storeApiPath string = 'store'

resource apim 'Microsoft.ApiManagement/service@2024-06-01-preview' existing = {
  name: apimName
}

resource logger 'Microsoft.ApiManagement/service/loggers@2024-06-01-preview' = {
  parent: apim
  name: 'whisker-appinsights-logger'
  properties: {
    loggerType: 'applicationInsights'
    credentials: { instrumentationKey: appInsightsInstrumentationKey }
    isBuffered: true
    resourceId: appInsightsId
  }
}

// Body bytes = 0: required for MCP streaming and avoids logging prompts/completions.
var diagnosticProperties = {
  loggerId: logger.id
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

resource globalDiagnostics 'Microsoft.ApiManagement/service/diagnostics@2024-06-01-preview' = if (configureGlobalDiagnostics) {
  parent: apim
  name: 'applicationinsights'
  properties: diagnosticProperties
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
  name: 'whisker-foundry-models'
  properties: {
    displayName: 'Whisker - Foundry Models (AI Gateway)'
    description: 'Governed access to Foundry model deployments (Azure OpenAI compatible).'
    path: modelsApiPath
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
    value: loadTextContent('../../apim/policies/models-api-policy.xml')
  }
  dependsOn: [ modelsBackend, contentSafetyBackend ]
}

resource modelsDiagnostics 'Microsoft.ApiManagement/service/apis/diagnostics@2024-06-01-preview' = if (!configureGlobalDiagnostics) {
  parent: modelsApi
  name: 'applicationinsights'
  properties: diagnosticProperties
}

// --- REST API that becomes the MCP server (Layer 2: Tools) ------------------
resource storeApi 'Microsoft.ApiManagement/service/apis@2024-06-01-preview' = {
  parent: apim
  name: 'whisker-works-api'
  properties: {
    displayName: 'Whisker Works Store API'
    description: 'Products, inventory, orders and cat facts for the Whisker Works store.'
    path: storeApiPath
    protocols: [ 'https' ]
    format: 'openapi+json'
    value: loadTextContent('../../src/catstore-api/openapi.json')
    serviceUrl: 'https://${catstoreHostName}/api'
    subscriptionRequired: true
  }
}

resource storeDiagnostics 'Microsoft.ApiManagement/service/apis/diagnostics@2024-06-01-preview' = if (!configureGlobalDiagnostics) {
  parent: storeApi
  name: 'applicationinsights'
  properties: diagnosticProperties
}

// --- Products & subscriptions (IDs are referenced by the policies) ----------
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
  properties: { displayName: 'Whisker demo - Bronze', scope: bronze.id, state: 'active' }
}

resource subGold 'Microsoft.ApiManagement/service/subscriptions@2024-06-01-preview' = {
  parent: apim
  name: 'whisker-demo-gold'
  properties: { displayName: 'Whisker demo - Gold', scope: gold.id, state: 'active' }
}

resource subA2A 'Microsoft.ApiManagement/service/subscriptions@2024-06-01-preview' = {
  parent: apim
  name: 'whisker-a2a-agent-internal'
  properties: { displayName: 'Whisker A2A agent (internal)', scope: gold.id, state: 'active' }
}

output gatewayUrl string = apim.properties.gatewayUrl
output a2aSubscriptionName string = subA2A.name
