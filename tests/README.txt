Offline tests - nothing here touches real windows or sends input.

  python tests/scroll_sim.py     frozen scrolling capture vs. the old manual mode on a simulated page
                                 (videos, hover preview, sticky header, smooth scrolling)
  python tests/scroll_cases.py   harder cases: slow smooth scroll, scroll messages, huge video,
                                 undo, an app that ignores scrolling
