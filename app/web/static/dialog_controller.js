(function () {
  let dependencies = Object.freeze({});

  function configure(options = {}) {
    dependencies = Object.freeze({ ...options });
    return window.UcpDialogController;
  }

  function dispose() {
    dependencies = Object.freeze({});
  }

  window.UcpDialogController = Object.freeze({ configure, dispose });
})();
