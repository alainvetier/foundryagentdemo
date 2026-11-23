// Optional, additive Topic 11B deployment, shared by NEW and EXISTING demo environments.
targetScope = 'resourceGroup'

param location string = resourceGroup().location
param foundryAccountName string
param foundryResourceGroup string = resourceGroup().name
param projectName string = 'whisker-works'
param appInsightsName string
param monitoringResourceGroup string = resourceGroup().name
param workspaceName string
param workspaceResourceGroup string = monitoringResourceGroup
param apimName string
param apimResourceGroup string = resourceGroup().name
param apimPrincipalId string
param apimClientId string
param apiClientId string
param modelDeployment string = 'gpt-4.1-mini'
@secure()
param apimSubscriptionKey string
@description('Empty bootstraps the registry/environment; set to an immutable tag after building the image.')
param imageTag string = ''

var suffix = take(uniqueString(resourceGroup().id), 6)
var tags = union(resourceGroup().tags ?? {}, { demo: 'whisker-topic-11b' })
var projectEndpoint = 'https://${foundryAccountName}.services.ai.azure.com/api/projects/${projectName}'

resource appInsights 'Microsoft.Insights/components@2020-02-02' existing = {
  name: appInsightsName
  scope: resourceGroup(monitoringResourceGroup)
}
resource workspace 'Microsoft.OperationalInsights/workspaces@2023-09-01' existing = {
  name: workspaceName
  scope: resourceGroup(workspaceResourceGroup)
}
resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'whisker-ops-id-${suffix}'
  location: location
  tags: tags
}
resource registry 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: 'whiskeraca${suffix}'
  location: location
  tags: tags
  sku: { name: 'Basic' }
  properties: { adminUserEnabled: false }
}
resource pull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(registry.id, identity.id, 'AcrPull')
  scope: registry
  properties: {
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '7f951dda-4ed3-4680-a7ca-43fe172d538d')
  }
}
module foundryAccess 'modules/external-agent-access.bicep' = {
  name: 'whisker-aca-foundry-access'
  scope: resourceGroup(foundryResourceGroup)
  params: {
    foundryAccountName: foundryAccountName
    principalId: identity.properties.principalId
  }
}
resource environment 'Microsoft.App/managedEnvironments@2025-01-01' = {
  name: 'whisker-ops-env-${suffix}'
  location: location
  tags: tags
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: workspace.properties.customerId
        sharedKey: workspace.listKeys().primarySharedKey
      }
    }
    workloadProfiles: [{ name: 'Consumption', workloadProfileType: 'Consumption' }]
  }
}
resource app 'Microsoft.App/containerApps@2025-01-01' = if (!empty(imageTag)) {
  name: 'whisker-ops-${suffix}'
  location: location
  tags: tags
  identity: { type: 'UserAssigned', userAssignedIdentities: { '${identity.id}': {} } }
  properties: {
    managedEnvironmentId: environment.id
    workloadProfileName: 'Consumption'
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: { external: true, targetPort: 8080, transport: 'http', allowInsecure: false }
      registries: [{ server: registry.properties.loginServer, identity: identity.id }]
      secrets: [
        { name: 'apim-gold-key', value: apimSubscriptionKey }
        { name: 'appinsights', value: appInsights.properties.ConnectionString }
      ]
    }
    template: {
      containers: [{
        name: 'kernel-panic'
        image: '${registry.properties.loginServer}/kernel-panic-aca:${imageTag}'
        resources: { cpu: json('0.5'), memory: '1Gi' }
        env: [
          { name: 'AZURE_CLIENT_ID', value: identity.properties.clientId }
          { name: 'FOUNDRY_PROJECT_ENDPOINT', value: projectEndpoint }
          { name: 'AZURE_AI_MODEL_DEPLOYMENT_NAME', value: modelDeployment }
          { name: 'APIM_GATEWAY_URL', value: 'https://${apimName}.azure-api.net' }
          { name: 'APIM_MCP_PATH', value: 'whisker-mcp' }
          { name: 'APIM_SUBSCRIPTION_KEY', secretRef: 'apim-gold-key' }
          { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', secretRef: 'appinsights' }
          { name: 'OTEL_SERVICE_NAME', value: 'kernel-panic-aca' }
        ]
        probes: [
          { type: 'Readiness', httpGet: { path: '/health', port: 8080 }, initialDelaySeconds: 10, periodSeconds: 10 }
          { type: 'Liveness', httpGet: { path: '/health', port: 8080 }, initialDelaySeconds: 30, periodSeconds: 30 }
        ]
      }]
      scale: { minReplicas: 1, maxReplicas: 1 }
    }
  }
  dependsOn: [pull, foundryAccess]
}
resource auth 'Microsoft.App/containerApps/authConfigs@2025-01-01' = if (!empty(imageTag)) {
  parent: app
  name: 'current'
  properties: {
    platform: { enabled: true }
    globalValidation: { unauthenticatedClientAction: 'Return401' }
    httpSettings: { requireHttps: true }
    identityProviders: {
      azureActiveDirectory: {
        enabled: true
        registration: {
          clientId: apiClientId
          openIdIssuer: '${az.environment().authentication.loginEndpoint}${tenant().tenantId}/v2.0'
        }
        validation: {
          allowedAudiences: ['api://${apiClientId}', apiClientId]
          defaultAuthorizationPolicy: {
            allowedApplications: [apimClientId]
            allowedPrincipals: { identities: [apimPrincipalId] }
          }
        }
      }
    }
  }
}
module gateway 'modules/external-agent-gateway.bicep' = if (!empty(imageTag)) {
  name: 'whisker-aca-gateway'
  scope: resourceGroup(apimResourceGroup)
  params: {
    apimName: apimName
    backendUrl: 'https://${app!.properties.configuration.ingress.fqdn}'
    backendAudience: 'api://${apiClientId}'
  }
  dependsOn: [auth]
}

output registryName string = registry.name
output registryEndpoint string = registry.properties.loginServer
output containerAppName string = 'whisker-ops-${suffix}'
output containerAppUrl string = empty(imageTag) ? '' : 'https://${app!.properties.configuration.ingress.fqdn}'
output gatewayUrl string = 'https://${apimName}.azure-api.net/whisker-ops'
output environmentName string = environment.name
output identityName string = identity.name
