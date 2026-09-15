/* Observation only. Fixed storage; no application allocations are modified.
 * All >=64KiB requests, plus one in 1024 smaller requests. Frame-pointer
 * stacks are best-effort, not a complete unwind. */
#include <gum/guminterceptor.h>
#include <gum/gummemory.h>
#include <glib.h>
#include <string.h>
#define CAP 32768
typedef struct { guint32 p,size,birth,stack[6]; } Entry;
typedef struct { GMutex lock; guint32 epoch,sequence,dropped,allocs,frees,reallocs; Entry entries[CAP]; } State;
extern State state;
typedef struct { guint32 old,size,selected,birth,stack[6]; } Pending;
static Entry *lookup(guint32 p, int insert) {
  guint32 i=(p>>4)&(CAP-1),j;
  for(j=0;j<CAP;j++,i=(i+1)&(CAP-1)) {
    Entry *e=&state.entries[i];
    if(e->p==p)return e;
    if(e->p==0)return insert?e:NULL;
  }
  return NULL;
}
static void remove_entry(Entry *e) {
  guint32 hole=(guint32)(e-state.entries),i=(hole+1)&(CAP-1),n;
  for(n=0;n<CAP-1;n++,i=(i+1)&(CAP-1)) {
    Entry *next=&state.entries[i]; if(!next->p)break;
    guint32 home=(next->p>>4)&(CAP-1);
    if(((i-home)&(CAP-1))>=((i-hole)&(CAP-1))) {
      state.entries[hole]=*next; hole=i;
    }
  }
  state.entries[hole].p=0;
}
static void capture(GumInvocationContext *ic,Pending *p) {
  guint32 frame=ic->cpu_context->ebp,i;
  p->stack[0]=(guint32)gum_invocation_context_get_return_address(ic);
  for(i=1;i<6;i++) {
    gsize n=0; guint32 *words;
    if(!frame || (frame&3))break;
    words=(guint32 *)gum_memory_read((guint8 *)frame,8,&n);
    if(!words || n!=8) { if(words)g_free(words); break; }
    guint32 next=words[0],ret=words[1]; g_free(words);
    p->stack[i]=ret;
    if(next<=frame || next-frame>1048576)break;
    frame=next;
  }
}
void alloc_enter(GumInvocationContext *ic) {
  Pending *p=gum_invocation_context_get_listener_invocation_data(ic,sizeof(Pending));
  memset(p,0,sizeof(*p)); p->size=(guint32)gum_invocation_context_get_nth_argument(ic,0);
  g_mutex_lock(&state.lock); state.allocs++;
  p->selected=p->size>=65536 || (++state.sequence%1024)==0; p->birth=state.epoch;
  g_mutex_unlock(&state.lock); if(p->selected)capture(ic,p);
}
void realloc_enter(GumInvocationContext *ic) {
  Pending *p=gum_invocation_context_get_listener_invocation_data(ic,sizeof(Pending));
  memset(p,0,sizeof(*p)); p->old=(guint32)gum_invocation_context_get_nth_argument(ic,0);
  p->size=(guint32)gum_invocation_context_get_nth_argument(ic,1);
  g_mutex_lock(&state.lock); state.reallocs++;
  Entry *e=p->old?lookup(p->old,0):NULL;
  p->selected=e!=NULL || p->size>=65536 || (++state.sequence%1024)==0;
  p->birth=e?e->birth:state.epoch;
  if(e)memcpy(p->stack,e->stack,sizeof(p->stack));
  g_mutex_unlock(&state.lock); if(p->selected && !p->stack[0])capture(ic,p);
}
void alloc_leave(GumInvocationContext *ic) {
  Pending *p=gum_invocation_context_get_listener_invocation_data(ic,sizeof(Pending));
  guint32 result=(guint32)gum_invocation_context_get_return_value(ic);
  g_mutex_lock(&state.lock);
  if(p->old && (result || p->size==0)) { Entry *old=lookup(p->old,0); if(old)remove_entry(old); }
  if(result && p->selected) {
    Entry *e=lookup(result,1);
    if(e) { e->p=result; e->size=p->size; e->birth=p->birth; memcpy(e->stack,p->stack,sizeof(e->stack)); }
    else state.dropped++;
  }
  g_mutex_unlock(&state.lock);
}
void free_enter(GumInvocationContext *ic) {
  guint32 p=(guint32)gum_invocation_context_get_nth_argument(ic,0);
  g_mutex_lock(&state.lock); state.frees++;
  Entry *e=p?lookup(p,0):NULL; if(e)remove_entry(e);
  g_mutex_unlock(&state.lock);
}
void snapshot(void *output,guint32 epoch) {
  g_mutex_lock(&state.lock); memcpy(output,&state,sizeof(State)); state.epoch=epoch; g_mutex_unlock(&state.lock);
}
guint32 state_size(void) { return sizeof(State); }
guint32 entries_offset(void) { return (guint32)((char *)&state.entries-(char *)&state); }
guint32 counters_offset(void) { return (guint32)((char *)&state.epoch-(char *)&state); }
/* Called only before installing hooks, against the tracer's empty storage. */
guint32 self_test(void) {
  guint32 i,p;
  for(i=0;i<128;i++) {
    p=((i*CAP+CAP-4)<<4); Entry *e=lookup(p,1);
    if(!e)return 1; e->p=p; e->size=i;
  }
  for(i=0;i<128;i+=2) {
    p=((i*CAP+CAP-4)<<4); Entry *e=lookup(p,0);
    if(!e || e->size!=i)return 2; remove_entry(e);
  }
  for(i=1;i<128;i+=2) {
    p=((i*CAP+CAP-4)<<4); Entry *e=lookup(p,0);
    if(!e || e->size!=i)return 3; remove_entry(e);
  }
  for(i=0;i<100000;i++) {
    p=(i+1)<<4; Entry *e=lookup(p,1);
    if(!e)return 4; e->p=p; remove_entry(e);
    if(lookup(p,0))return 5;
  }
  for(i=0;i<CAP;i++)if(state.entries[i].p)return 6;
  memset(&state,0,sizeof(State)); return 0;
}
