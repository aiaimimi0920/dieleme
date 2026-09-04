const actions = Object.create(null);

export function registerActions(nextActions) {
  Object.assign(actions, nextActions);
}

export function callAction(name, ...args) {
  const action = actions[name];
  if (typeof action !== "function") {
    throw new Error(`desktop action is not registered: ${name}`);
  }
  return action(...args);
}
