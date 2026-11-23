targetScope = 'resourceGroup'

param appInsightsName string
param projectPrincipalId string
param projectResourceId string

var roleLogAnalyticsReader = '73c42c96-874c-492b-b04d-ab87d138a893'
var rolePrivilegedMonitoringDataReader = 'dbc9c667-e97f-4491-aee6-90b9cf960190'

resource appInsights 'Microsoft.Insights/components@2020-02-02' existing = {
  name: appInsightsName
}

resource appInsightsReaderRoles 'Microsoft.Authorization/roleAssignments@2022-04-01' = [
  for roleDefinitionId in [
    roleLogAnalyticsReader
    rolePrivilegedMonitoringDataReader
  ]: {
    scope: appInsights
    name: guid(projectResourceId, appInsights.id, roleDefinitionId)
    properties: {
      principalId: projectPrincipalId
      principalType: 'ServicePrincipal'
      roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleDefinitionId)
    }
  }
]
