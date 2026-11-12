Fixed

Use UTF-8 for CLI agent, code/plugin runner and command grader pipes regardless of the parent locale, preserving Unicode answers and JSON grading inputs. Invalid UTF-8 output raises an explicit adapter error instead of corrupting answers or scores (#973).
