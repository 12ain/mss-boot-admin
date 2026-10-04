import { createStyles } from 'antd-style';

export const useAvatarMenuStyles = createStyles(({ token }) => ({
  panel: {
    background: token.colorBgElevated,
    borderRadius: token.borderRadiusLG,
    boxShadow: token.boxShadowSecondary,
    color: token.colorText,
    maxHeight: 'calc(100dvh - 80px)',
    maxWidth: 'calc(100vw - 24px)',
    overflowWrap: 'anywhere',
    overflowY: 'auto',
    width: 320,
  },
  content: {
    display: 'flex',
    flexDirection: 'column',
    gap: token.marginSM,
    minWidth: 0,
    padding: token.padding,
  },
  menu: {
    borderBlockStart: `${token.lineWidth}px solid ${token.colorBorderSecondary}`,
  },
}));
