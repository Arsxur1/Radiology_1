/**
 * Конфигурация OHIF Viewer v3 (ТЗ, раздел 4: OHIF на Cornerstone3D).
 * Источник данных — обезличенный Orthanc (clean) через DICOMweb шлюза medviz.
 * MPR, объёмный рендер, оконные пресеты, измерения — штатные режимы OHIF.
 *
 * Адреса вычисляются от хоста, с которого открыт OHIF: на ПК врача «localhost»
 * указывал бы на его же компьютер. Шлюз (:80) сам авторизуется в clean-Orthanc,
 * поэтому пароль Orthanc в браузер не попадает.
 */
var MEDVIZ_GATEWAY = window.location.protocol + '//' + window.location.hostname;

window.config = {
  name: 'medviz',
  // Вход через Keycloak клиники (тот же, что у рабочего места врача); токен OHIF отправляет
  // в DICOMweb, а шлюз проверяет его на backend.
  oidc: [
    {
      authority: window.location.protocol + '//' + window.location.hostname + ':8080/realms/medviz',
      client_id: 'medviz-ohif',
      redirect_uri: '/callback',
      response_type: 'code',
      scope: 'openid',
      post_logout_redirect_uri: '/',
    },
  ],
  routerBasename: '/',
  // Обязательные ключи v3: пустые списки — стандартные расширения и режимы образа.
  extensions: [],
  modes: [],
  customizationService: {},
  showStudyList: true,
  maxNumberOfWebWorkers: 3,
  showWarningMessageForCrossOrigin: false,
  showCPUFallbackMessage: true,
  showLoadingIndicator: true,
  strictZSpacingForVolumeViewport: true,
  maxNumRequests: { interaction: 100, thumbnail: 5, prefetch: 25 },
  showErrorDetails: 'always',
  defaultDataSourceName: 'medviz',
  dataSources: [
    {
      namespace: '@ohif/extension-default.dataSourcesModule.dicomweb',
      sourceName: 'medviz',
      configuration: {
        friendlyName: 'medviz (обезличенный контур)',
        name: 'orthanc-clean',
        wadoUriRoot: MEDVIZ_GATEWAY + '/wado',
        qidoRoot: MEDVIZ_GATEWAY + '/dicom-web',
        wadoRoot: MEDVIZ_GATEWAY + '/dicom-web',
        qidoSupportsIncludeField: false,
        imageRendering: 'wadors',
        thumbnailRendering: 'wadors',
        enableStudyLazyLoad: true,
        supportsFuzzyMatching: false,
        supportsWildcard: true,
        // Только чтение: шлюз всё равно запрещает запись в DICOMweb.
        dicomUploadEnabled: false,
        supportsReject: false,
        omitQuotationForMultipartRequest: true,
        bulkDataURI: { enabled: true },
      },
    },
  ],
};
