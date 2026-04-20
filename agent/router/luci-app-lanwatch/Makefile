#
# LuCI Lua Package for LanWatch Agent
#

include $(TOPDIR)/rules.mk

LUCI_TITLE:=LanWatch 网络监控 - LuCI 管理界面
LUCI_PKGARCH:=all
LUCI_DEPENDS:=+curl +ip +ping

define Package/luci-app-lanwatch
    SECTION:=luci
    CATEGORY:=LuCI
    SUBMENU:=服务
    TITLE:=LanWatch 网络监控
    DEPENDS:=+curl +ip +ping +bash
endef

define Build/Prepare
    mkdir -p $(PKG_BUILD_DIR)
endef

define Build/Compile
    # Shell 脚本无需编译
endef

define Package/luci-app-lanwatch/install
    $(CP) ./root/* $(1)/
    chmod +x $(1)/etc/lanwatch/router_agent.sh
endef

$(eval $(call BuildPackage,luci-app-lanwatch))
