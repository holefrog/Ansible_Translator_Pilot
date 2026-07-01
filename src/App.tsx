import React from "react";

export default function App() {
  return (
    <div className="min-h-screen bg-white text-gray-800 flex flex-col items-center justify-center p-8 font-sans">
      <div className="max-w-md text-center space-y-4">
        <h1 className="text-xl font-bold tracking-tight text-black">Translator Pilot (Stage 1)</h1>
        <p className="text-sm text-gray-500">
          This project is configured as a pure Python backend pipeline with Ansible deployment playbooks for ThinkPad T14.
        </p>
        <div className="p-3 bg-gray-50 border border-gray-200 rounded font-mono text-xs text-left text-gray-600">
          <p>📁 python/ — Core Translation & Alignment Pipeline</p>
          <p>📁 ansible/ — Automated Provisioning & Deployment Playbook</p>
          <p>📄 settings.toml — Pipeline Configurations</p>
        </div>
      </div>
    </div>
  );
}
