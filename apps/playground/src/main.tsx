import React from "react";
import { createRoot } from "react-dom/client";
import { App } from "./workbench/App";
import "./workbench/styles.css";

const root = document.getElementById("root");
if (!root) throw new Error("Playground root element is missing.");

createRoot(root).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
