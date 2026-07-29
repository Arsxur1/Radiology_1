/**
 * Конфигурация OHIF Viewer (ТЗ, раздел 4: OHIF на Cornerstone3D).
 * Источник данных — обезличенный Orthanc (clean) через DICOMweb.
 * Осевые/коронарные/сагиттальные проекции, MPR, объёмный рендер, оконные пресеты.
 */
window.config = {
  routerBasename: '/',
  showStudyList: true,
  // На этапе 1 виден только обезличенный контур.
  dataSources: [
    {
      friendlyName: 'medviz (обезличенный)',
      namespace: '@ohif/extension-default.dataSourcesModule.dicomweb',
      sourceName: 'dicomweb',
      configuration: {
        name: 'orthanc-clean',
        wadoUriRoot: 'http://localhost:8043/wado',
        qidoRoot: 'http://localhost:8043/dicom-web',
        wadoRoot: 'http://localhost:8043/dicom-web',
        qidoSupportsIncludeField: true,
        supportsReject: false,
        supportsFuzzyMatching: false,
        supportsWildcard: true,
        omitQuotationForMultipartRequest: true,
      },
    },
  ],
  defaultDataSourceName: 'dicomweb',
  // Баннер напоминает: не для клинического применения на этапе RESEARCH.
  whiteLabeling: {
    createLogoComponentFn: function () {
      return null;
    },
  },
  i18n: { defaultLanguage: 'ru' },
};
