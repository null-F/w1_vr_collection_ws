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
	{ 0x2d3a3de6, "idr_destroy" },
	{ 0x9ec69abc, "usb_deregister" },
	{ 0x92997ed8, "_printk" },
	{ 0x50ccff5f, "tty_driver_kref_put" },
	{ 0xf3d0fa17, "tty_unregister_driver" },
	{ 0x21bb1252, "usb_register_driver" },
	{ 0xd0d6e9e6, "tty_register_driver" },
	{ 0x67b27ec1, "tty_std_termios" },
	{ 0x3dce0e7, "__tty_alloc_driver" },
	{ 0x6cbbfc54, "__arch_copy_to_user" },
	{ 0x908e5601, "cpu_hwcaps" },
	{ 0xa447cd5b, "remove_wait_queue" },
	{ 0x1000e51, "schedule" },
	{ 0xe26dc993, "add_wait_queue" },
	{ 0xaad8c7d6, "default_wake_function" },
	{ 0xc6cbbc89, "capable" },
	{ 0x12a4e128, "__arch_copy_from_user" },
	{ 0xa94df22c, "tty_flip_buffer_push" },
	{ 0x7f40d275, "tty_insert_flip_string_fixed_flag" },
	{ 0xc703e0b2, "tty_port_register_device" },
	{ 0xa85d0bba, "usb_get_intf" },
	{ 0xb7b2d71a, "usb_driver_claim_interface" },
	{ 0x44ea151f, "usb_alloc_urb" },
	{ 0xca6ecc56, "usb_alloc_coherent" },
	{ 0xdcb764ad, "memset" },
	{ 0xdcac85b, "tty_port_init" },
	{ 0xc4c38c8c, "__mutex_rt_init" },
	{ 0x5be2fdf8, "rt_mutex_base_init" },
	{ 0x1329e1b1, "__init_waitqueue_head" },
	{ 0x16a28313, "idr_alloc" },
	{ 0x3e43398c, "usb_ifnum_to_if" },
	{ 0x275b45d6, "usb_put_intf" },
	{ 0x3385493a, "idr_remove" },
	{ 0x3ea1b6e4, "__stack_chk_fail" },
	{ 0x409873e3, "tty_termios_baud_rate" },
	{ 0x6c257ac0, "tty_termios_hw_change" },
	{ 0xc5b6f236, "queue_work_on" },
	{ 0x2d3385d3, "system_wq" },
	{ 0x296695f, "refcount_warn_saturate" },
	{ 0x8c842397, "tty_standard_install" },
	{ 0x69f38847, "cpu_hwcap_keys" },
	{ 0x14b89635, "arm64_const_caps_ready" },
	{ 0x20ab2529, "idr_find" },
	{ 0x37a0cba, "kfree" },
	{ 0x5819878e, "kmem_cache_alloc_trace" },
	{ 0x81913b3, "kmalloc_caches" },
	{ 0x1e4a8e59, "usb_control_msg" },
	{ 0x2c341b43, "usb_autopm_get_interface" },
	{ 0x8c558c80, "tty_port_open" },
	{ 0x349c5f14, "tty_port_close" },
	{ 0xb84899ea, "usb_anchor_urb" },
	{ 0xbf2817a6, "usb_autopm_get_interface_async" },
	{ 0x4829a47e, "memcpy" },
	{ 0xde7d7b84, "tty_port_hangup" },
	{ 0x90d4dff, "tty_port_tty_wakeup" },
	{ 0xac3d531d, "usb_get_from_anchor" },
	{ 0x3dc89d62, "usb_autopm_put_interface" },
	{ 0x348aad05, "usb_autopm_get_interface_no_resume" },
	{ 0x52b8c208, "tty_port_tty_hangup" },
	{ 0x6ebe366f, "ktime_get_mono_fast_ns" },
	{ 0xf1c9caaf, "_dev_info" },
	{ 0x1cfa0c38, "usb_driver_release_interface" },
	{ 0xa6bcdaab, "usb_free_coherent" },
	{ 0x2316892c, "usb_free_urb" },
	{ 0xce1b3d2f, "tty_unregister_device" },
	{ 0xf1c85323, "tty_kref_put" },
	{ 0x749fc0fd, "tty_vhangup" },
	{ 0x789210f5, "tty_port_tty_get" },
	{ 0x59a1c185, "mutex_unlock" },
	{ 0x5f0a4a48, "__wake_up" },
	{ 0xdf486fb6, "mutex_lock" },
	{ 0x823e63df, "tty_port_put" },
	{ 0x3c12dfe, "cancel_work_sync" },
	{ 0x56b8f699, "usb_kill_urb" },
	{ 0x177bc627, "rt_spin_unlock" },
	{ 0x383f0a73, "rt_spin_lock" },
	{ 0x4b0a3f52, "gic_nonsecure_priorities" },
	{ 0x9c2ae45f, "usb_autopm_put_interface_async" },
	{ 0x284db7ff, "_dev_err" },
	{ 0x406009f7, "usb_submit_urb" },
	{ 0x1fdc7df2, "_mcount" },
};

MODULE_INFO(depends, "");

MODULE_ALIAS("usb:v1A86p7523d*dc*dsc*dp*ic*isc*ip*in*");
MODULE_ALIAS("usb:v1A86p7522d*dc*dsc*dp*ic*isc*ip*in*");
MODULE_ALIAS("usb:v1A86p5523d*dc*dsc*dp*ic*isc*ip*in*");
MODULE_ALIAS("usb:v1A86pE523d*dc*dsc*dp*ic*isc*ip*in*");
MODULE_ALIAS("usb:v4348p5523d*dc*dsc*dp*ic*isc*ip*in*");

MODULE_INFO(srcversion, "57CBAB2FAEE984ADC883DE8");
