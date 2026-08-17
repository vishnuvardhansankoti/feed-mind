import App from "./App.svelte";
import { mount } from "svelte";
import "./app.css";
import { initAnalytics } from "./lib/analytics.js";

initAnalytics(); // no-op unless VITE_GA_MEASUREMENT_ID is set (prod builds only)

const app = mount(App, { target: document.getElementById("app") });

export default app;
