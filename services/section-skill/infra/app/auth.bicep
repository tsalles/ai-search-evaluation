param functionName string
param applicationClientId string
param searchCallerClientId string
param searchCallerObjectId string
param tenantId string

resource functionApp 'Microsoft.Web/sites@2024-04-01' existing = {
  name: functionName
}

resource authentication 'Microsoft.Web/sites/config@2024-04-01' = {
  parent: functionApp
  name: 'authsettingsV2'
  properties: {
    platform: {
      enabled: true
      runtimeVersion: '~1'
    }
    globalValidation: {
      requireAuthentication: true
      unauthenticatedClientAction: 'Return401'
      redirectToProvider: 'azureactivedirectory'
    }
    httpSettings: {
      requireHttps: true
    }
    identityProviders: {
      azureActiveDirectory: {
        enabled: true
        registration: {
          clientId: applicationClientId
          openIdIssuer: 'https://login.microsoftonline.com/${tenantId}/v2.0'
        }
        validation: {
          allowedAudiences: [
            applicationClientId
            'api://${applicationClientId}'
          ]
          defaultAuthorizationPolicy: {
            allowedApplications: [searchCallerClientId]
            allowedPrincipals: {
              identities: [searchCallerObjectId]
            }
          }
        }
      }
    }
    login: {
      tokenStore: {
        enabled: false
      }
    }
  }
}
