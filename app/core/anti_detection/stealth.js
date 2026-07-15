(function () {
  "use strict";

  const defineGetter = (target, prop, getter) => {
    try {
      Object.defineProperty(target, prop, {
        configurable: true,
        enumerable: true,
        get: getter,
      });
    } catch (_) {
      // 部分浏览器把指纹属性设为不可配置；单项失败不应中断页面脚本。
    }
  };

  const patchFunction = (target, prop, replacement) => {
    try {
      const original = target && target[prop];
      if (typeof original !== "function") {
        return;
      }
      const wrapped = replacement(original);
      Object.defineProperty(wrapped, "toString", {
        value: () => original.toString(),
        configurable: true,
      });
      target[prop] = wrapped;
    } catch (_) {
      // 某个接口无法包装时保留原实现，避免隐匿补丁破坏页面执行。
    }
  };

  const navigatorPrototype = Navigator.prototype;

  defineGetter(navigatorPrototype, "webdriver", () => undefined);
  defineGetter(navigatorPrototype, "languages", () => ["zh-CN", "zh", "en-US", "en"]);
  defineGetter(navigatorPrototype, "hardwareConcurrency", () => 8);
  defineGetter(navigatorPrototype, "deviceMemory", () => 8);

  const pluginData = [
    { name: "PDF Viewer", filename: "internal-pdf-viewer", description: "Portable Document Format" },
    { name: "Chrome PDF Viewer", filename: "internal-pdf-viewer", description: "Portable Document Format" },
    { name: "Chromium PDF Viewer", filename: "internal-pdf-viewer", description: "Portable Document Format" },
    { name: "Microsoft Edge PDF Viewer", filename: "internal-pdf-viewer", description: "Portable Document Format" },
    { name: "WebKit built-in PDF", filename: "internal-pdf-viewer", description: "Portable Document Format" },
  ];

  const makePluginArray = () => {
    const plugins = pluginData.map((plugin) => Object.freeze({ ...plugin }));
    Object.defineProperty(plugins, "item", {
      value: (index) => plugins[index] || null,
      configurable: true,
    });
    Object.defineProperty(plugins, "namedItem", {
      value: (name) => plugins.find((plugin) => plugin.name === name) || null,
      configurable: true,
    });
    Object.defineProperty(plugins, "refresh", {
      value: () => undefined,
      configurable: true,
    });
    return plugins;
  };

  defineGetter(navigatorPrototype, "plugins", makePluginArray);
  defineGetter(navigatorPrototype, "mimeTypes", () => {
    const mimeTypes = [
      Object.freeze({
        type: "application/pdf",
        suffixes: "pdf",
        description: "Portable Document Format",
        enabledPlugin: makePluginArray()[0],
      }),
    ];
    Object.defineProperty(mimeTypes, "item", {
      value: (index) => mimeTypes[index] || null,
      configurable: true,
    });
    Object.defineProperty(mimeTypes, "namedItem", {
      value: (name) => mimeTypes.find((item) => item.type === name) || null,
      configurable: true,
    });
    return mimeTypes;
  });

  if (!window.chrome) {
    Object.defineProperty(window, "chrome", {
      configurable: true,
      enumerable: true,
      value: {
        app: { isInstalled: false, InstallState: {}, RunningState: {} },
        csi: () => ({}),
        loadTimes: () => ({}),
        runtime: {},
      },
    });
  }

  if (navigator.permissions && navigator.permissions.query) {
    patchFunction(navigator.permissions, "query", (original) => function query(parameters) {
      if (parameters && parameters.name === "notifications") {
        const state = Notification.permission === "denied" ? "denied" : "prompt";
        return Promise.resolve({ state, onchange: null });
      }
      return original.apply(this, arguments);
    });
  }

  const cloneCanvas = (canvas) => {
    const copy = document.createElement("canvas");
    copy.width = canvas.width;
    copy.height = canvas.height;
    const ctx = copy.getContext("2d");
    if (ctx) {
      ctx.drawImage(canvas, 0, 0);
      const width = Math.max(1, Math.min(32, copy.width));
      const height = Math.max(1, Math.min(32, copy.height));
      try {
        const imageData = ctx.getImageData(0, 0, width, height);
        const pixelCount = width * height;
        const sampleCount = Math.min(8, pixelCount);
        for (let sample = 0; sample < sampleCount; sample += 1) {
          const pixel = (sample * 97) % pixelCount;
          const red = pixel * 4;
          imageData.data[red] = (imageData.data[red] + 1 + (sample % 2)) % 256;
        }
        ctx.putImageData(imageData, 0, 0);
      } catch (_) {
        // 跨域画布读取像素会抛错，此时退回未扰动的副本。
      }
    }
    return copy;
  };

  if (window.HTMLCanvasElement) {
    patchFunction(HTMLCanvasElement.prototype, "toDataURL", (original) => function toDataURL() {
      return original.apply(cloneCanvas(this), arguments);
    });
    patchFunction(HTMLCanvasElement.prototype, "toBlob", (original) => function toBlob() {
      return original.apply(cloneCanvas(this), arguments);
    });
  }

  if (window.CanvasRenderingContext2D) {
    patchFunction(CanvasRenderingContext2D.prototype, "getImageData", (original) => function getImageData() {
      const imageData = original.apply(this, arguments);
      if (imageData && imageData.data && imageData.data.length > 0) {
        imageData.data[0] = (imageData.data[0] + 1) % 255;
      }
      return imageData;
    });
  }

  const patchWebGL = (prototype) => {
    if (!prototype) {
      return;
    }
    patchFunction(prototype, "getParameter", (original) => function getParameter(parameter) {
      if (parameter === 37445) {
        return "Intel Inc.";
      }
      if (parameter === 37446) {
        return "Intel(R) UHD Graphics";
      }
      return original.apply(this, arguments);
    });
  };
  patchWebGL(window.WebGLRenderingContext && WebGLRenderingContext.prototype);
  patchWebGL(window.WebGL2RenderingContext && WebGL2RenderingContext.prototype);

  if (window.Intl && Intl.DateTimeFormat) {
    patchFunction(Intl.DateTimeFormat.prototype, "resolvedOptions", (original) => function resolvedOptions() {
      const options = original.apply(this, arguments);
      options.locale = options.locale || "zh-CN";
      options.timeZone = options.timeZone || "Asia/Shanghai";
      return options;
    });
  }
})();
