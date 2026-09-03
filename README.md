# Minimax-H3-SkillMD-TG-bot

A multimodal Telegram bot built with Python and Gemini 3.6 Flash that automatically converts text ideas, images, videos, and audio into structured generation prompts tailored for the **MiniMax H3 (Hailuo AI)** video generation engine. 

Designed specifically for fine art figure studies, creative prompt expansion, and precise shot architecture, the bot ingests custom rulesets (`skill.md` and reference guides) to output standard MiniMax H3 formats across text-to-video (T2VA), image-to-video (I2VA), and full reference workflows.

---

## Core Capabilities

* **Multimodal Input Parsing:** Processes plain text, photos, `.mp4` video clips, video notes, `.mp3`/`.wav`/`.ogg` audio files, and Telegram voice messages.
* **MiniMax H3 Prompt Formatting:** Structures output into specialized MiniMax H3 fields, including `subject_definitions`, `retention_analysis`, `integrated_multimodal_description`, camera movements, timing breakdowns, `overall_soundscape`, dialogue tags `<d>`, and non-diegetic audio/music queues.
* **Artistic & Figure Analysis:** Utilizes un-throttled safety configurations (`BLOCK_NONE`) across harm categories to ensure objective visual breakdown of artistic erotica, figure studies, anatomical poses, and complex lighting.
* **Dynamic Instruction Architecture:** Injecting system-level instructions directly from repository markdown and text files (`skill.md`, `references/base-en.txt`, `references/ref-en.txt`) to enforce exact syntax and camera movement standards.
* **Render Keep-Alive Endpoint:** Runs a concurrent background Flask HTTP server (port `8080`) allowing cloud hosting platforms like Render to maintain 24/7 uptime when pinged by monitoring services like UptimeRobot.

---

## Project Structure

```text
├── bot.py                  # Main Telegram bot polling loop & Flask keep-alive server
├── skill.md                # Primary MiniMax H3 prompt engineering ruleset
├── references/             # Supplementary syntax & shot definition guides
│   ├── base-en.txt         # Base instruction patterns & shot definitions
│   └── ref-en.txt          # Reference mode standards & soundscape formats
├── requirements.txt        # Dependencies (python-telegram-bot, google-genai, flask)
└── README.md
