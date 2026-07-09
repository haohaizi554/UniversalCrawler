(function () {
  let dependencies = Object.freeze({});

  function configure(options = {}) {
    dependencies = Object.freeze({ ...options });
    return window.UcpSettingsController;
  }

  function dispose() {
    dependencies = Object.freeze({});
  }

  window.UcpSettingsController = Object.freeze({ configure, dispose });
})();
