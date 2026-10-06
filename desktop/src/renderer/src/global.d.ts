export {};

declare global {
  interface Window {
    homuncula: {
      health: () => Promise<any>;
      installOllama: () => Promise<any>;
      restartHost: () => Promise<any>;
      state: () => Promise<any>;
      pauseAutonomy: () => Promise<any>;
      resumeAutonomy: () => Promise<any>;
      threads: () => Promise<any[]>;
      messages: (threadId: string) => Promise<any[]>;
      createThread: (title: string) => Promise<any>;
      chat: (threadId: string, content: string) => Promise<any>;
      responsibilities: () => Promise<any[]>;
      createResponsibility: (
        title: string,
        objective: string,
        proactiveMode?: string
      ) => Promise<any>;
      updateResponsibility: (
        id: string,
        patch: { status?: string; proactive_mode?: string }
      ) => Promise<any>;
      actions: (status?: string) => Promise<any[]>;
      approve: (id: string) => Promise<any>;
      deny: (id: string) => Promise<any>;
      execute: (id: string) => Promise<any>;
      activity: () => Promise<any[]>;
      findings: (status?: string) => Promise<any[]>;
      memory: (query?: string) => Promise<any[]>;
      reviseMemory: (
        id: string,
        content: string,
        reason: string,
        kind?: string,
        confidence?: number
      ) => Promise<any>;
      grants: () => Promise<any[]>;
      addGrant: (
        capability: string,
        resourcePattern: string,
        expiresAt?: string
      ) => Promise<any>;
      revokeGrant: (id: string) => Promise<any>;
      processes: () => Promise<any[]>;
      subscriptions: () => Promise<any[]>;
      plans: () => Promise<any[]>;
      skills: () => Promise<any[]>;
      verification: () => Promise<any[]>;
      models: () => Promise<any>;
      selectModel: (model: string) => Promise<any>;
      pullModel: (model: string) => Promise<any>;
      computerStatus: () => Promise<any>;
      windows: () => Promise<any>;
    };
  }
}
