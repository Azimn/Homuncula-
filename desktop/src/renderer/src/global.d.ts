export {};

declare global {
  interface Window {
    homuncula: {
      health: () => Promise<any>;
      state: () => Promise<any>;
      threads: () => Promise<any[]>;
      createThread: (title: string) => Promise<any>;
      chat: (threadId: string, content: string) => Promise<any>;
      responsibilities: () => Promise<any[]>;
      createResponsibility: (title: string, objective: string) => Promise<any>;
      actions: (status?: string) => Promise<any[]>;
      approve: (id: string) => Promise<any>;
      deny: (id: string) => Promise<any>;
      execute: (id: string) => Promise<any>;
      activity: () => Promise<any[]>;
    };
  }
}
