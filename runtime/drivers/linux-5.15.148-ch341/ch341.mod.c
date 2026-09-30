#include <linux/module.h>
#define INCLUDE_VERMAGIC
#include <linux/build-salt.h>
#include <linux/elfnote-lto.h>
#include <linux/vermagic.h>
#include <linux/compiler.h>

BUILD_SALT;
BUILD_LTO_INFO;

MODULE_INFO(vermagic, VERMAGIC_STRING);
MODULE_INFO(name, KBUILD_MODNAME);

__visible struct module __this_module
__section(".gnu.linkonce.this_module") = {
	.name = KBUILD_MODNAME,
	.init = init_module,
#ifdef CONFIG_MODULE_UNLOAD
	.exit = cleanup_module,
#endif
	.arch = MODULE_ARCH_INIT,
};

#ifdef CONFIG_RETPOLINE
MODULE_INFO(retpoline, "Y");
#endif

static const struct modversion_info ____versions[]
__used __section("__versions") = {
	{ 0xed7d3979, "module_layout" },
	{ 0x2d5edfc6, "usb_serial_generic_tiocmiwait" },
	{ 0x9900fdf5, "usb_serial_deregister_drivers" },
	{ 0x88b40f09, "usb_serial_register_drivers" },
	{ 0xcf26a1a7, "usb_serial_generic_open" },
	{ 0x30e74134, "tty_termios_copy_hw" },
	{ 0x409873e3, "tty_termios_baud_rate" },
	{ 0x6c257ac0, "tty_termios_hw_change" },
	{ 0x40b6a757, "tty_put_char" },
	{ 0x54496b4, "schedule_timeout_interruptible" },
	{ 0x15ba50a6, "jiffies" },
	{ 0xf1c9caaf, "_dev_info" },
	{ 0x5be2fdf8, "rt_mutex_base_init" },
	{ 0xbf093a33, "usb_serial_generic_resume" },
	{ 0x5819878e, "kmem_cache_alloc_trace" },
	{ 0x81913b3, "kmalloc_caches" },
	{ 0x1e4a8e59, "usb_control_msg" },
	{ 0x284db7ff, "_dev_err" },
	{ 0xf1c85323, "tty_kref_put" },
	{ 0xe26b8c55, "usb_serial_handle_dcd_change" },
	{ 0x789210f5, "tty_port_tty_get" },
	{ 0x5f0a4a48, "__wake_up" },
	{ 0x406009f7, "usb_submit_urb" },
	{ 0x56b8f699, "usb_kill_urb" },
	{ 0xa572df, "usb_serial_generic_close" },
	{ 0x37a0cba, "kfree" },
	{ 0x177bc627, "rt_spin_unlock" },
	{ 0x383f0a73, "rt_spin_lock" },
	{ 0x1fdc7df2, "_mcount" },
};

MODULE_INFO(depends, "usbserial");

MODULE_ALIAS("usb:v1A86p5523d*dc*dsc*dp*ic*isc*ip*in*");
MODULE_ALIAS("usb:v1A86p7522d*dc*dsc*dp*ic*isc*ip*in*");
MODULE_ALIAS("usb:v1A86p7523d*dc*dsc*dp*ic*isc*ip*in*");
MODULE_ALIAS("usb:v2184p0057d*dc*dsc*dp*ic*isc*ip*in*");
MODULE_ALIAS("usb:v4348p5523d*dc*dsc*dp*ic*isc*ip*in*");
MODULE_ALIAS("usb:v9986p7523d*dc*dsc*dp*ic*isc*ip*in*");
