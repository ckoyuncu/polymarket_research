module.exports = {
  apps: [
    {
      name: "polymarket-production",
      script: "run_production.py",
      interpreter: "./venv/bin/python",
      cwd: "/Users/shem/Desktop/polymarket_starter/polymarket_starter",
      
      // Arguments - customize these
      args: [
        "Account88888",
        "-c", "300",
        "--poll-interval", "10"
      ],
      
      // Auto-restart settings
      autorestart: true,
      watch: false,
      max_restarts: 10,
      restart_delay: 30000,  // 30 seconds between restarts
      
      // Logging
      log_file: "./logs/combined.log",
      out_file: "./logs/out.log",
      error_file: "./logs/error.log",
      log_date_format: "YYYY-MM-DD HH:mm:ss Z",
      merge_logs: true,
      
      // Environment
      env: {
        NODE_ENV: "production",
        PYTHONUNBUFFERED: "1"
      },
      
      // Resource limits
      max_memory_restart: "500M",
      
      // Graceful shutdown
      kill_timeout: 10000,
      wait_ready: true,
      listen_timeout: 10000
    }
  ]
};
