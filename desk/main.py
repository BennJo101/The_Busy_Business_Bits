# The Busy Business Bits - desk unit.
# Ctrl-C on the serial port drops to the REPL if you want to poke at it.
try:
    import desk
    desk.Desk().run()
except KeyboardInterrupt:
    print("desk stopped")
except Exception as e:
    try:                     # never leave the screen dead and unexplained
        import tft
        d = tft.TFT()
        ink, paper = d.rgb(26, 17, 22), d.rgb(216, 207, 192)
        d.clear(ink)
        d.text("the desk fell over:", 8, 90, d.rgb(232, 217, 184), ink)
        d.text(str(e)[:38], 8, 110, paper, ink)
    except Exception:
        pass
    raise
