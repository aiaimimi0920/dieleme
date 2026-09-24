/** Preserve the stored type; identifier-shaped strings must remain strings. */
export function parseEditableValue(rawValue: string, originalType = "string"): unknown {
  if (originalType === "string") return rawValue;
  const value = rawValue.trim();
  if (value === "") return null;
  if (originalType === "number") {
    const number = Number(value);
    if (!Number.isFinite(number) || (Number.isInteger(number) && !Number.isSafeInteger(number))) {
      throw new Error("请输入有效且精度安全的数值");
    }
    return number;
  }
  if (originalType === "boolean") {
    if (value === "true" || value === "是") return true;
    if (value === "false" || value === "否") return false;
    throw new Error("布尔字段只能填写 true、false、是或否");
  }
  if (originalType === "object") {
    const parsed: unknown = JSON.parse(value);
    if (parsed === null || typeof parsed === "object") return parsed;
    throw new Error("结构化字段必须填写 JSON 对象或数组");
  }
  return rawValue;
}
