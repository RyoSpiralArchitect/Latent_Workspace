# Run on the Mac (mac2) from the repository root, at the commit recorded in the README.
# Keys: ~/.config/ltws/judge.env (mode 600), loaded into the environment only; never recorded.
R=provenance/beta/ltws_beta_generation_20261018
G=$R/generation/generations.jsonl
Q=$BOOLQ   # boolq_validation.jsonl, SHA-256 dbad2984…88b68
set -a; source ~/.config/ltws/judge.env; set +a
.venv/bin/python scripts/judge_ltws_beta_examples.py run --folder $R/judge --generations $G --boolq $Q \
  --provider openai --model gpt-6.1-sol --effort medium --max-output-tokens 8000 --workers 8
.venv/bin/python scripts/judge_ltws_beta_examples.py run --folder $R/judge --generations $G --boolq $Q \
  --provider mistral --model mistral-large-4 --temperature 0.2 --max-output-tokens 16000 --workers 12
.venv/bin/python scripts/judge_ltws_beta_examples.py run --folder $R/judge --generations $G --boolq $Q \
  --provider gemini --model gemini-3.1-pro-preview --max-output-tokens 16000 --workers 8
# The three ran concurrently, each as its own process (see TIMELINE.log); Gemini started
# later, once its key was available.
# Gemini 3.1 Pro (preview) stopped at what looks like a daily quota (~250 requests): kept, incomplete,
# in incomplete/. Gemini was then run with gemini-3.8-flash, from commit 4624ef7 (retries
# honor the provider's retryDelay):
.venv/bin/python scripts/judge_ltws_beta_examples.py run --folder $R/judge --generations $G --boolq $Q \
  --provider gemini --model gemini-3.8-flash --max-output-tokens 16000 --workers 6
