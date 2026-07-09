(function () {
  let dependencies = Object.freeze({});

  function configure(options = {}) {
    dependencies = Object.freeze({ ...options });
    return window.UcpListPages;
  }

  function dispose() {
    dependencies = Object.freeze({});
  }

  window.UcpListPages = Object.freeze({ configure, dispose });
})();
