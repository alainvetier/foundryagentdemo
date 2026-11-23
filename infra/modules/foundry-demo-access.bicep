// Grants access on an EXISTING Foundry account/project and optionally adds the demo model deployments
// (deployed at the Foundry resource group scope).
targetScope = 'resourceGroup'

param foundryAccountName string
param projectName string
param createModelDeployments bool = true
param chatModelName string
param chatModelVersion string
param newModelName string
param newModelVersion string
param modelCapacity int
param newModelCapacity int
param apimPrincipalId string
param storefrontPrincipalId string
param deployerPrincipalId string = ''

var roleAzureAIUser = '53ca6127-db72-4b80-b1b0-d745d6d5456d'
var roleFoundryProjectManager = 'eadc314b-1a2d-4efa-be10-5d325db5065e'
var roleCognitiveServicesOpenAIUser = '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd'
var roleCognitiveServicesUser = 'a97b65f3-24c7-4388-baec-2e87135dc908'

resource foundry 'Microsoft.CognitiveServices/accounts@2025-06-01' existing = {
  name: foundryAccountName
}

resource project 'Microsoft.CognitiveServices/accounts/projects@2025-06-01' existing = {
  parent: foundry
  name: projectName
}

resource chatDeployment 'Microsoft.CognitiveServices/accounts/deployments@2025-06-01' = if (createModelDeployments) {
  parent: foundry
  name: chatModelName
  sku: { name: 'GlobalStandard', capacity: modelCapacity }
  properties: {
    model: { format: 'OpenAI', name: chatModelName, version: chatModelVersion }
  }
}

resource newDeployment 'Microsoft.CognitiveServices/accounts/deployments@2025-06-01' = if (createModelDeployments) {
  parent: foundry
  name: newModelName
  sku: { name: 'GlobalStandard', capacity: newModelCapacity }
  properties: {
    model: { format: 'OpenAI', name: newModelName, version: newModelVersion }
  }
  dependsOn: [ chatDeployment ]
}

resource apimOpenAIUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: foundry
  name: guid(foundry.id, apimPrincipalId, roleCognitiveServicesOpenAIUser)
  properties: {
    principalId: apimPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleCognitiveServicesOpenAIUser)
  }
}

resource apimCognitiveUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: foundry
  name: guid(foundry.id, apimPrincipalId, roleCognitiveServicesUser)
  properties: {
    principalId: apimPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleCognitiveServicesUser)
  }
}

resource storefrontAIUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: foundry
  name: guid(foundry.id, storefrontPrincipalId, roleAzureAIUser)
  properties: {
    principalId: storefrontPrincipalId
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

resource deployerProjectManager 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(deployerPrincipalId)) {
  scope: project
  name: guid(project.id, deployerPrincipalId, roleFoundryProjectManager)
  properties: {
    principalId: deployerPrincipalId
    principalType: 'User'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleFoundryProjectManager)
  }
}

output projectPrincipalId string = project.identity.principalId
output projectResourceId string = project.id
