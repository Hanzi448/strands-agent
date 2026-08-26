import { useState, useEffect, useRef } from 'react';
import AppLayout from '@cloudscape-design/components/app-layout';
import TopNavigation from '@cloudscape-design/components/top-navigation';
import ContentLayout from '@cloudscape-design/components/content-layout';
import Container from '@cloudscape-design/components/container';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Box from '@cloudscape-design/components/box';
import Button from '@cloudscape-design/components/button';
import Grid from '@cloudscape-design/components/grid';
import ChatBubble from '@cloudscape-design/chat-components/chat-bubble';
import Avatar from '@cloudscape-design/chat-components/avatar';
import LoadingBar from '@cloudscape-design/chat-components/loading-bar';
import LiveRegion from '@cloudscape-design/components/live-region';
import Icon from '@cloudscape-design/components/icon';
import Alert from '@cloudscape-design/components/alert';
import Flashbar from '@cloudscape-design/components/flashbar';
import { useVoiceAgent } from './hooks/useVoiceAgent';
import { getCurrentUser, signOut } from './auth';

interface AuthUser {
  email: string;
}

function App() {
  const isLocalDev = (import.meta as any).env.VITE_LOCAL_DEV === 'true';

  // Voice agent hook
  const voiceAgent = useVoiceAgent();

  // Ref for auto-scrolling chat container
  const chatContainerRef = useRef<HTMLDivElement>(null);

  // All hooks declared at the top level to maintain consistent order
  const [error, setError] = useState('');
  const [user, setUser] = useState<AuthUser | null>(null);
  const [showAuthModal, setShowAuthModal] = useState(false);
  const [checkingAuth, setCheckingAuth] = useState(true);
  const [AuthModalComponent, setAuthModalComponent] = useState<any>(null);
  const [showWelcomeFlashbar, setShowWelcomeFlashbar] = useState(true);

  // Authentication effect
  useEffect(() => {
    if (isLocalDev) {
      // Skip authentication in local development mode
      setCheckingAuth(false);
      setUser({ email: 'local-dev@example.com' } as AuthUser);
    } else {
      checkAuth();
    }
  }, [isLocalDev]);

  // Auto-scroll to bottom when conversation history changes
  useEffect(() => {
    if (chatContainerRef.current) {
      chatContainerRef.current.scrollTop = chatContainerRef.current.scrollHeight;
    }
  }, [voiceAgent.conversationHistory, voiceAgent.isSpeaking]);

  // AuthModal loading effect
  useEffect(() => {
    if (!isLocalDev && showAuthModal && !AuthModalComponent) {
      import('./AuthModal').then(module => {
        setAuthModalComponent(() => module.default);
      });
    }
  }, [showAuthModal, AuthModalComponent, isLocalDev]);

  const checkAuth = async () => {
    if (isLocalDev) return;

    try {
      const currentUser = await getCurrentUser();
      setUser(currentUser);
    } catch (err) {
      setUser(null);
    } finally {
      setCheckingAuth(false);
    }
  };

  const handleSignOut = async () => {
    if (isLocalDev) return;

    try {
      signOut();
    } catch (err) {
      console.error('Error signing out:', err);
    }
    setUser(null);
  };

  const handleAuthSuccess = async () => {
    setShowAuthModal(false);
    await checkAuth();
  };

  const [isConnecting, setIsConnecting] = useState(false);

  const handleMainClick = async () => {
    if (!voiceAgent.isConnected && !isConnecting) {
      setShowWelcomeFlashbar(false); // Dismiss flashbar when starting
      setIsConnecting(true);
      try {
        await voiceAgent.connect();
        // Auto-start recording after connection
        setTimeout(() => {
          voiceAgent.startRecording();
        }, 1000);
      } finally {
        setIsConnecting(false);
      }
    }
  };

  const handleStop = (e: React.MouseEvent) => {
    e.stopPropagation();
    voiceAgent.disconnect();
  };

  if (checkingAuth) {
    return (
      <>
        <TopNavigation
          identity={{
            href: "#",
            title: "Nova Sonic Voice Agent"
          }}
          utilities={[
            {
              type: "button",
              text: user ? `${user.email} | Sign Out` : "Sign In",
              iconName: user ? "user-profile" : "lock-private",
              onClick: () => {
                if (user) {
                  handleSignOut();
                } else {
                  setShowAuthModal(true);
                }
              }
            }
          ]}
          i18nStrings={{
            overflowMenuTriggerText: "More",
            overflowMenuTitleText: "All"
          }}
        />
        <AppLayout
          navigationHide={true}
          toolsHide={true}
          disableContentPaddings
          contentType="default"
          content={
            <ContentLayout defaultPadding>
              <Box textAlign="center" padding="xxl">
                Loading...
              </Box>
            </ContentLayout>
          }
        />
      </>
    );
  }

  return (
    <>
      {!isLocalDev && AuthModalComponent && (
        <AuthModalComponent
          visible={showAuthModal}
          onDismiss={() => setShowAuthModal(false)}
          onSuccess={handleAuthSuccess}
        />
      )}
      <TopNavigation
        identity={{
          href: "#",
          title: isLocalDev
            ? "Nova Sonic Voice Agent (Local Dev)"
            : "Nova Sonic Voice Agent"
        }}
        utilities={isLocalDev ? [
          {
            type: "button",
            text: "Local Development",
            iconName: "settings"
          }
        ] : [
          {
            type: "button",
            text: user ? `${user.email} | Sign Out` : "Sign In",
            iconName: user ? "user-profile" : "lock-private",
            onClick: () => {
              if (user) {
                handleSignOut();
              } else {
                setShowAuthModal(true);
              }
            }
          }
        ]}
        i18nStrings={{
          overflowMenuTriggerText: "More",
          overflowMenuTitleText: "All"
        }}
      />
      <AppLayout
        navigationHide={true}
        toolsHide={true}
        disableContentPaddings
        contentType="default"
        content={
          <ContentLayout defaultPadding>
            <Grid
              gridDefinition={[
                { colspan: { default: 12, xs: 1, s: 2 } },
                { colspan: { default: 12, xs: 10, s: 8 } },
                { colspan: { default: 12, xs: 1, s: 2 } }
              ]}
            >
              <div />
              <SpaceBetween size="l">
                {voiceAgent.error ? (
                  <Alert 
                    type="error" 
                    dismissible 
                    onDismiss={voiceAgent.clearError}
                  >
                    {voiceAgent.error}
                  </Alert>
                ) : null}
                {error ? (
                  <Alert type="error" dismissible onDismiss={() => setError('')}>
                    {error}
                  </Alert>
                ) : null}
                {voiceAgent.conversationHistory.length === 0 && showWelcomeFlashbar && (
                  <Flashbar
                    items={[
                      {
                        type: 'info',
                        content: user 
                          ? 'Start a voice conversation with the AI assistant. Click "Start Chatting" below to begin.'
                          : 'Start a voice conversation with the AI assistant. Sign in or sign up to start chatting.',
                        dismissible: true,
                        onDismiss: () => setShowWelcomeFlashbar(false),
                      }
                    ]}
                  />
                )}
                <Container>
                  <SpaceBetween size="m">
                    {/* Chat History Area */}
                    <div 
                      ref={chatContainerRef}
                      style={{ minHeight: '300px', maxHeight: '500px', overflowY: 'auto' }}
                    >
                      {voiceAgent.conversationHistory.length === 0 ? null : (
                        <SpaceBetween size="xs">
                          {voiceAgent.conversationHistory.map((turn, index) => {
                            // Show loading bar on last assistant message if agent is still speaking
                            const showLoading = 
                              turn.role === 'assistant' && 
                              index === voiceAgent.conversationHistory.length - 1 &&
                              voiceAgent.isSpeaking;

                            return (
                              <ChatBubble
                                key={`history-${index}`}
                                type={turn.role === 'user' ? 'outgoing' : 'incoming'}
                                ariaLabel={`${turn.role === 'user' ? 'User' : 'AI Assistant'} message at ${new Date().toLocaleTimeString()}`}
                                showLoadingBar={showLoading}
                                avatar={
                                  turn.role === 'user' ? (
                                    <Avatar 
                                      ariaLabel="Benjamin Lecoq" 
                                      tooltipText="Benjamin Lecoq"
                                      initials="BL" 
                                    />
                                  ) : (
                                    <Avatar 
                                      ariaLabel="Generative AI assistant" 
                                      tooltipText="Generative AI assistant"
                                      iconName="gen-ai" 
                                      color="gen-ai" 
                                    />
                                  )
                                }
                              >
                                {turn.transcript}
                              </ChatBubble>
                            );
                          })}
                        </SpaceBetween>
                      )}
                    </div>

                    {/* Fixed Button with Nested Audio Bar */}
                    <div style={{ borderTop: '1px solid #e9ebed', paddingTop: '16px' }}>
                      {!voiceAgent.isRecording ? (
                        <Button
                          variant="primary"
                          iconName="microphone"
                          onClick={handleMainClick}
                          fullWidth
                          disabled={!user || isConnecting || voiceAgent.isConnected}
                          loading={isConnecting || (voiceAgent.isConnected && !voiceAgent.isRecording)}
                        >
                          {isConnecting || (voiceAgent.isConnected && !voiceAgent.isRecording) ? 'Connecting...' : 'Start Chatting'}
                        </Button>
                      ) : (
                        <div
                          style={{
                            width: '100%',
                            padding: '10px 12px',
                            border: '2px solid #0972d3',
                            borderRadius: '8px',
                            backgroundColor: '#ffffff',
                            display: 'flex',
                            alignItems: 'center',
                            gap: '8px',
                            boxSizing: 'border-box',
                            minHeight: '40px'
                          }}
                        >
                          {/* Microphone Icon */}
                          <div style={{ 
                            flexShrink: 0,
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            color: '#0972d3'
                          }}>
                            <Icon name="microphone" size="normal" />
                          </div>

                          {/* Audio Bar (nested inside button) */}
                          <div style={{ 
                            flex: 1,
                            minWidth: 0,
                            overflow: 'hidden'
                          }}>
                            <LiveRegion>
                              <LoadingBar variant="gen-ai" />
                            </LiveRegion>
                          </div>

                          <Button
                            variant="icon"
                            iconName="stop-circle"
                            onClick={handleStop}
                            ariaLabel="Stop conversation"
                          />
                        </div>
                      )}
                    </div>
                  </SpaceBetween>
                </Container>
              </SpaceBetween>
              <div />
            </Grid>
          </ContentLayout>
        }
      />
    </>
  );
}

export default App;
