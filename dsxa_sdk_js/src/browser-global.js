import { DSXAClient, DSXAHttpError } from "./index.js";

if (typeof window !== "undefined") {
  window.DSXASDK = { DSXAClient, DSXAHttpError };
}
