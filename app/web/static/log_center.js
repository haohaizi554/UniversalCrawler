(function () {
  let dependencies = Object.freeze({});

  function configure(options = {}) {
    dependencies = Object.freeze({ ...options });
    return window.UcpLogCenter;
  }

  function dispose() {
    dependencies = Object.freeze({});
  }

  window.UcpLogCenter = Object.freeze({ configure, dispose });
})();
