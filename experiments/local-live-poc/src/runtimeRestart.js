// Process recovery is independent of model readiness. An experiment may still
// need its explicit model-start action after the Gateway comes back.
export async function waitForGatewayRestart(previousInstanceId, {
  getHealth,
  sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
  now = () => performance.now(),
  timeoutMs = 120000,
} = {}) {
  const deadline = now() + timeoutMs;
  let sawOffline = false;
  while (now() < deadline) {
    await sleep(Math.min(500, deadline - now()));
    let health;
    try {
      health = await getHealth(Math.max(1, Math.min(2000, deadline - now())));
    } catch {
      sawOffline = true;
      continue;
    }
    if (health?.service !== "local-live-caption-gateway") continue;
    const newInstance = health.runtimeInstanceId
      && health.runtimeInstanceId !== previousInstanceId;
    if (newInstance || (!previousInstanceId && sawOffline)) return health;
  }
  throw new Error("Gateway 未能在 120 秒内重新连接");
}
