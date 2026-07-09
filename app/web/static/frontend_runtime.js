(function () {
  let dependencies = Object.freeze({});

  function configure(options = {}) {
    dependencies = Object.freeze({ ...options });
    return window.UcpFrontendRuntime;
  }

  function dispose() {
    dependencies = Object.freeze({});
  }

  window.UcpFrontendRuntime = Object.freeze({ configure, dispose });
})();
