// Toolkit 1.1.19의 --interactive false만으로는 MSAL 재로그인이 차단되지 않는다.
// 공식 CLI와 동일한 외부 MSAL 모듈에서 모든 대화형/새 로그인 진입점을 차단한다.
"use strict";

const { createRequire } = require("node:module");
const toolkitRequire = createRequire(process.argv[1]);
const { PublicClientApplication } = toolkitRequire("@azure/msal-node");
const blocked = async () => {
    throw new Error("EASM: authentication preparation required; automatic login is disabled.");
};
for (const name of [
    "acquireTokenInteractive",
    "acquireTokenByDeviceCode",
    "acquireTokenByUsernamePassword",
    "getAuthCodeUrl",
    "acquireTokenByCode",
]) {
    if (typeof PublicClientApplication.prototype[name] !== "function") {
        throw new Error("EASM: unsupported MSAL authentication surface.");
    }
    Object.defineProperty(PublicClientApplication.prototype, name, {
        value: blocked,
        writable: false,
        configurable: false,
    });
}
