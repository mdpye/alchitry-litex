#!/usr/bin/env python3

from migen import *

from litex.build.io import DDROutput
from litex.build.generic_platform import *
from litex.build.xilinx import XilinxPlatform

from litex.soc.integration.soc_core import *
from litex.soc.integration.soc_sdram import *
from litex.soc.integration.builder import *

from litex.soc.cores.clock import S6PLL
from litex.soc.cores.uart import UARTWishboneBridge
from litex.soc.cores import dna

from litedram.modules import MT48LC32M8
from litedram.phy import HalfRateGENSDRPHY, GENSDRPHY

from litex.soc.cores.led import LedChaser

import os
import argparse

_io = [
    # Clk / Rst
    ("clk50", 0, Pins("P56"), IOStandard("LVTTL")),
    ("cpu_reset", 0, Pins("P38"), IOStandard("LVTTL")),

    # Leds
    ("user_led", 0, Pins("P134"), IOStandard("LVTTL")),
    ("user_led", 1, Pins("P133"), IOStandard("LVTTL")),
    ("user_led", 2, Pins("P132"), IOStandard("LVTTL")),
    ("user_led", 3, Pins("P131"), IOStandard("LVTTL")),
    ("user_led", 4, Pins("P127"), IOStandard("LVTTL")),
    ("user_led", 5, Pins("P126"), IOStandard("LVTTL")),
    ("user_led", 6, Pins("P124"), IOStandard("LVTTL")),
    ("user_led", 7, Pins("P123"), IOStandard("LVTTL")),

    # uart
    ("serial", 0,
        Subsignal("tx", Pins("P50")),
        Subsignal("rx", Pins("P51")),
        IOStandard("LVTTL")
    ),

    # avr signals
    ("tx_busy", 0, Pins("P39"), IOStandard("LVTTL")),
    ("cclk", 0, Pins("P70"), IOStandard("LVTTL")),

    # sdram (HDMI shield)
    ("sdram_clock", 0, Pins("P29"), IOStandard("LVTTL"), Misc("SLEW=FAST")),
    ("sdram", 0,
        Subsignal("a", Pins("P101 P102 P104 P105 P5 P6 P7 P8 P9 P10 P88 P27 P26")),
        Subsignal("dq", Pins("P75 P78 P79 P80 P34 P35 P40 P41")),
        Subsignal("ba", Pins("P85 P87")),
        Subsignal("dm", Pins("P74")),
        Subsignal("ras_n", Pins("P83")),
        Subsignal("cas_n", Pins("P82")),
        Subsignal("we_n", Pins("P81")),
        Subsignal("cs_n", Pins("P84")),
        Subsignal("cke", Pins("P30")),
        IOStandard("LVTTL"),
        Misc("SLEW = FAST")
    ),
]

# Platform -----------------------------------------------------------------------------------------

class Platform(XilinxPlatform):
    default_clk_name   = "clk50"
    default_clk_period = 1e9/50e6

    def __init__(self):
        XilinxPlatform.__init__(self, "xc6slx9-3-tqg144", _io)
        self.toolchain.additional_commands = ["write_bitstream -force -bin_file {build_name}"]

    def do_finalize(self, fragment):
        XilinxPlatform.do_finalize(self, fragment)
        self.add_period_constraint(self.lookup_request("clk50", loose=True), 1e9/50e6)

# CRG ----------------------------------------------------------------------------------------------

class _CRG(Module):
    def __init__(self, platform, sys_clk_freq):
        self.clock_domains.cd_sys      = ClockDomain()
        self.clock_domains.cd_sys_ps   = ClockDomain(reset_less=True)
        #self.clock_domains.cd_sys2x    = ClockDomain()
        #self.clock_domains.cd_sys2x_ps = ClockDomain(reset_less=True)

        # PLL
        self.submodules.pll = pll = S6PLL(speedgrade=-2)
        self.comb += pll.reset.eq(~platform.request("cpu_reset") | ~platform.request("cclk"))
        pll.register_clkin(platform.request("clk50"), 50e6)
        pll.create_clkout(self.cd_sys,      sys_clk_freq)
        pll.create_clkout(self.cd_sys_ps,   sys_clk_freq, phase=90)
        #pll.create_clkout(self.cd_sys2x,    2*sys_clk_freq)
        #pll.create_clkout(self.cd_sys2x_ps, 2*sys_clk_freq, phase=90)

        # SDRAM clock
        self.specials += DDROutput(1, 0, platform.request("sdram_clock"), ClockSignal("sys_ps"))
        #self.specials += DDROutput(1, 0, platform.request("sdram_clock"), ClockSignal("sys2x_ps"))

# SoC ----------------------------------------------------------------------------------------------

class BaseSoC(SoCCore):
    def __init__(self, sys_clk_freq=int(66666666), **kwargs):
        platform = Platform()

        SoCCore.__init__(self, platform, sys_clk_freq,
            ident="Mojo V3 SoC",
            ident_version=True,
            **kwargs)

        self.submodules.crg = _CRG(platform, sys_clk_freq)

        # SDR SDRAM --------------------------------------------------------------------------------
        if not self.integrated_main_ram_size:
            self.submodules.sdrphy = GENSDRPHY(platform.request("sdram"))
            #self.submodules.sdrphy = HalfRateGENSDRPHY(platform.request("sdram"))
            self.add_sdram("sdram",
                phy                     = self.sdrphy,
                module                  = MT48LC32M8(sys_clk_freq, "1:1"),
                #module                  = MT48LC32M8(sys_clk_freq, "1:2"),
                origin                  = self.mem_map["main_ram"],
                size                    = 0x2000000,
                l2_cache_size           = 1024,
                l2_cache_min_data_width = 128,
                l2_cache_reverse        = True
            )

        # No CPU, use Serial to control Wishbone bus
        #self.submodules.serial_bridge = UARTWishboneBridge(platform.request("serial"), sys_clk_freq)
        #self.add_wb_master(self.serial_bridge.wishbone)

        # FPGA identification
        self.submodules.dna = dna.DNA()
        self.add_csr("dna")

        # Led
        self.submodules.leds = LedChaser(
            pads         = platform.request_all("user_led"),
            sys_clk_freq = sys_clk_freq)
        self.add_csr("leds")

soc = BaseSoC()

# Build --------------------------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="LiteX SoC on Mojo V3")
    parser.add_argument("--build",        action="store_true", help="Build bitstream")
    parser.add_argument("--sys-clk-freq", default=66666666,   help="System clock frequency (default: 30 MHz)")

    builder_args(parser)
    soc_sdram_args(parser)
    args = parser.parse_args()

    soc = BaseSoC(
        sys_clk_freq = int(args.sys_clk_freq),
        **soc_sdram_argdict(args)
    )
    builder = Builder(soc, **builder_argdict(args))
    builder.build(run=args.build)

if __name__ == "__main__":
    main()
