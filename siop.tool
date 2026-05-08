siop-tool/
  README.md
  .gitignore

  web/                       # Next.js (Vercel)
    package.json
    next.config.ts
    tsconfig.json
    tailwind.config.ts
    postcss.config.mjs
    app/
      layout.tsx
      page.tsx
    components/
      Dashboard.tsx
    lib/
      supabaseClient.ts
      kpi.ts
    .env.example

  streamlit/                 # Streamlit (Streamlit Cloud)
    streamlit_app.py
    requirements.txt
    .streamlit/
      config.toml
    .streamlit/
      secrets.toml.example
