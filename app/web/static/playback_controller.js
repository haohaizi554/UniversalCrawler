(function () {
  let dependencies = Object.freeze({});

  function configure(options = {}) {
    dependencies = Object.freeze({ ...options });
    return window.UcpPlaybackController;
  }

  function dispose() {
    dependencies = Object.freeze({});
  }

  window.UcpPlaybackController = Object.freeze({ configure, dispose });
})();
