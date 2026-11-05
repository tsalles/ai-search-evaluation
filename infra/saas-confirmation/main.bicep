targetScope = 'resourceGroup'

param location string = 'eastus'
param searchName string
param operatorPrincipalId string
param storageAccountName string = 'saexampledatasource'
param containerName string = 'container'
param cognitiveAccountName string = 'example'

var blobReaderRole = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '2a2b9908-6ea1-4ae2-8e65-a410df84e7d1')
var cognitiveUserRole = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'a97b65f3-24c7-4388-baec-2e87135dc908')
var openAIUserRole = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd')
var searchContributorRole = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '7ca78c08-252a-4471-8644-bb5ff32d4ba0')
var searchReaderRole = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '1407120a-92aa-4202-b7e9-c0e197c71c8f')

resource rawContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' existing = {
  name: '${storageAccountName}/default/${containerName}'
}

resource cognitive 'Microsoft.CognitiveServices/accounts@2023-05-01' existing = {
  name: cognitiveAccountName
}

module searchService 'br/public:avm/res/search/search-service:0.13.0' = {
  name: 'saas-confirmation-search-${uniqueString(resourceGroup().id, searchName)}'
  params: {
    name: searchName
    location: location
    sku: 'standard'
    enableTelemetry: false
    managedIdentities: {
      systemAssigned: true
    }
    replicaCount: 1
    partitionCount: 1
    hostingMode: 'Default'
    semanticSearch: 'standard'
    disableLocalAuth: true
    publicNetworkAccess: 'Enabled'
    tags: {
      purpose: 'independent-saas-retrieval-confirmation'
      owner: 'document-generator'
      corpusDomain: 'fictional-enterprise-saas'
    }
  }
}

resource search 'Microsoft.Search/searchServices@2025-05-01' existing = {
  name: searchName
}

resource sourceReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(rawContainer.id, search.id, blobReaderRole)
  scope: rawContainer
  properties: {
    roleDefinitionId: blobReaderRole
    principalId: searchService.outputs.systemAssignedMIPrincipalId!
    principalType: 'ServicePrincipal'
  }
}

resource cognitiveAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(cognitive.id, search.id, cognitiveUserRole)
  scope: cognitive
  properties: {
    roleDefinitionId: cognitiveUserRole
    principalId: searchService.outputs.systemAssignedMIPrincipalId!
    principalType: 'ServicePrincipal'
  }
}

resource embeddingAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(cognitive.id, search.id, openAIUserRole)
  scope: cognitive
  properties: {
    roleDefinitionId: openAIUserRole
    principalId: searchService.outputs.systemAssignedMIPrincipalId!
    principalType: 'ServicePrincipal'
  }
}

resource operatorSchemaAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(search.id, operatorPrincipalId, searchContributorRole)
  scope: search
  dependsOn: [searchService]
  properties: {
    roleDefinitionId: searchContributorRole
    principalId: operatorPrincipalId
    principalType: 'User'
  }
}

resource operatorQueryAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(search.id, operatorPrincipalId, searchReaderRole)
  scope: search
  dependsOn: [searchService]
  properties: {
    roleDefinitionId: searchReaderRole
    principalId: operatorPrincipalId
    principalType: 'User'
  }
}

output searchServiceId string = search.id
output searchEndpoint string = 'https://${search.name}.search.windows.net'
output searchPrincipalId string = searchService.outputs.systemAssignedMIPrincipalId!
output roleAssignmentIds array = [
  sourceReader.id
  cognitiveAccess.id
  embeddingAccess.id
  operatorSchemaAccess.id
  operatorQueryAccess.id
]
