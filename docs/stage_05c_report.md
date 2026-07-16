# Stage 05C 验收报告

状态：PASS（代码、自动化、性能和远程 HTTP 验证完成后提交）。

## 审核清单

1. schema 5 与 4→5 备份迁移；2. 原始 token 不入库；3. HttpOnly；4. SameSite=Lax；5. Path=/；6. Max-Age；7. Secure 可配置；8. 无 Cookie 拒绝 manifest；9. 无 Cookie 拒绝 page；10. 假 Cookie 拒绝；11. 错 alias 拒绝；12. 绝对过期；13. 空闲过期；14. 撤销；15. 动态旧会话锁版；16. 新进入读取新版；17. fixed 语义；18. trace 唯一；19. 水印逐会话不同；20. trace 在水印文本；21. token/IP 不在水印；22. 基础预览不变；23. 有效 WebP；24. ASCII 回退；25. capability 状态；26. manifest 429；27. page 429；28. 全局并发 6；29. 正常懒加载不误限；30. 最小访问事件；31. 事件保留清理；32. 无磁盘水印缓存；33. 管理查询；34. 管理撤销；35. 管理页不泄密；36. 原件隔离；37. 旧测试全量回归。

自动化结果：最终 `154 passed`，0 failed；仅 5 条第三方 SWIG 类型弃用警告。性能结果见 `stage_05c_performance_report.md`。

边界：限速和匿名水印不等于 DRM；不识别真实个人，也不能绝对阻止截图或录屏。未写入 QuickDrop、网络、Tailscale 或防火墙配置。
