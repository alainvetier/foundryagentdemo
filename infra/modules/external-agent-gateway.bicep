targetScope = 'resourceGroup'

param apimName string
param backendUrl string
param backendAudience string

resource apim 'Microsoft.ApiManagement/service@2024-06-01-preview' existing = {
  name: apimName
}
resource gold 'Microsoft.ApiManagement/service/products@2024-06-01-preview' existing = {
  parent: apim
  name: 'whisker-gold'
}
resource logger 'Microsoft.ApiManagement/service/loggers@2024-06-01-preview' existing = {
  parent: apim
  name: 'whisker-appinsights-logger'
}
resource api 'Microsoft.ApiManagement/service/apis@2024-06-01-preview' = {
  parent: apim
  name: 'whisker-ops-aca'
  properties: {
    displayName: 'Whisker - Kernel Panic on Container Apps (optional 11B)'
    description: 'Standalone read-only external agent. Foundry observes; APIM enforces gateway controls.'
    path: 'whisker-ops'
    protocols: ['https']
    subscriptionRequired: true
    serviceUrl: backendUrl
  }
}
resource chat 'Microsoft.ApiManagement/service/apis/operations@2024-06-01-preview' = {
  parent: api
  name: 'chat'
  properties: { displayName: 'Read-only operations summary', method: 'POST', urlTemplate: '/chat' }
}
resource health 'Microsoft.ApiManagement/service/apis/operations@2024-06-01-preview' = {
  parent: api
  name: 'health'
  properties: { displayName: 'Agent health', method: 'GET', urlTemplate: '/health' }
}
resource policy 'Microsoft.ApiManagement/service/apis/policies@2024-06-01-preview' = {
  parent: api
  name: 'policy'
  properties: {
    format: 'rawxml'
    value: replace(replace(loadTextContent('../../apim/policies/external-agent-policy.xml'), '__BACKEND_URL__', backendUrl), '__BACKEND_AUDIENCE__', backendAudience)
  }
}
resource productLink 'Microsoft.ApiManagement/service/products/apis@2024-06-01-preview' = {
  parent: gold
  name: api.name
}
resource diagnostic 'Microsoft.ApiManagement/service/apis/diagnostics@2024-06-01-preview' = {
  parent: api
  name: 'applicationinsights'
  properties: {
    loggerId: logger.id
    alwaysLog: 'allErrors'
    verbosity: 'information'
    sampling: { samplingType: 'fixed', percentage: 100 }
    frontend: { request: { body: { bytes: 0 } }, response: { body: { bytes: 0 } } }
    backend: { request: { body: { bytes: 0 } }, response: { body: { bytes: 0 } } }
  }
}
