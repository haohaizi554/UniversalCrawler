(function () {
  const MAX_VALUE = "9999";
  // Static contract labels: 1 页（推荐）, 20 篇笔记（推荐）, 20 个视频（推荐）, max.
  const UNITS = {
    pages: {
      label: "\u9875\u6570:",
      suffix: "\u9875",
      defaultValue: "1",
      options: [["1", true], ["2", false], ["3", false], ["5", false], [MAX_VALUE, false]],
    },
    notes: {
      label: "\u7b14\u8bb0\u6570:",
      suffix: "\u7bc7\u7b14\u8bb0",
      defaultValue: "20",
      options: [["10", false], ["20", true], ["30", false], ["50", false], [MAX_VALUE, false]],
    },
    videos: {
      label: "\u89c6\u9891\u6570:",
      suffix: "\u4e2a\u89c6\u9891",
      defaultValue: "20",
      options: [["10", false], ["20", true], ["30", false], ["50", false], [MAX_VALUE, false]],
    },
  };

  function normalizeUnit(unit) {
    return Object.prototype.hasOwnProperty.call(UNITS, unit) ? unit : "videos";
  }

  function countOptionLabel(value, unit) {
    const text = String(value || "");
    if (!text) return "";
    if (text === MAX_VALUE || text.toLowerCase() === "max") return "max";
    return `${text} ${UNITS[normalizeUnit(unit)].suffix}`;
  }

  function countFallbackOptions(unit) {
    const config = UNITS[normalizeUnit(unit)];
    return config.options.map(([value, recommended]) => ({
      value,
      label: recommended ? `${countOptionLabel(value, unit)}\uff08\u63a8\u8350\uff09` : countOptionLabel(value, unit),
    }));
  }

  function countLabelText(unit) {
    return UNITS[normalizeUnit(unit)].label;
  }

  function defaultCount(unit) {
    return UNITS[normalizeUnit(unit)].defaultValue;
  }

  window.UcpPlatformLimits = {
    maxValue: MAX_VALUE,
    normalizeUnit,
    countFallbackOptions,
    countOptionLabel,
    countLabelText,
    defaultCount,
  };
})();
