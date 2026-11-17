#ifndef S3_MOCK_DMA_H
#define S3_MOCK_DMA_H
#include <stdbool.h>
#include <stdint.h>
typedef unsigned int uint;
typedef struct { uint32_t ctrl_trig, transfer_count, al1_ctrl; } mock_dma_channel;
typedef struct { mock_dma_channel ch[12]; uint32_t abort; } mock_dma_hw;
typedef struct { int unused; } dma_channel_config;
extern mock_dma_hw *dma_hw;
extern unsigned mock_ack0, mock_ack1;
#define DMA_CH0_CTRL_TRIG_BUSY_BITS (1u << 24)
#define DMA_CH0_CTRL_TRIG_AHB_ERROR_BITS (1u << 31)
#define DMA_CH0_CTRL_TRIG_EN_BITS 1u
#define DMA_CH0_CTRL_TRIG_READ_ERROR_BITS (1u << 30)
#define DMA_CH0_CTRL_TRIG_WRITE_ERROR_BITS (1u << 29)
#define DMA_SIZE_32 2
#define __compiler_memory_barrier() __asm__ volatile ("" ::: "memory")
static inline int dma_claim_unused_channel(bool required) {(void)required;return -1;}
static inline void dma_channel_unclaim(uint c) {(void)c;}
static inline void dma_channel_set_irq0_enabled(uint c,bool e) {(void)c;(void)e;}
static inline void dma_channel_set_irq1_enabled(uint c,bool e) {(void)c;(void)e;}
static inline void dma_channel_acknowledge_irq0(uint c) {(void)c;++mock_ack0;}
static inline void dma_channel_acknowledge_irq1(uint c) {(void)c;++mock_ack1;}
static inline dma_channel_config dma_channel_get_default_config(uint c) {(void)c;return (dma_channel_config){0};}
static inline void channel_config_set_transfer_data_size(dma_channel_config *c,int s) {(void)c;(void)s;}
static inline void channel_config_set_read_increment(dma_channel_config *c,bool b) {(void)c;(void)b;}
static inline void channel_config_set_write_increment(dma_channel_config *c,bool b) {(void)c;(void)b;}
static inline void channel_config_set_dreq(dma_channel_config *c,uint d) {(void)c;(void)d;}
static inline void dma_channel_configure(uint c,const dma_channel_config *cfg,void *w,const void *r,uint n,bool start) {(void)c;(void)cfg;(void)w;(void)r;(void)n;(void)start;}
static inline bool dma_channel_is_busy(uint c) {return (dma_hw->ch[c].ctrl_trig & DMA_CH0_CTRL_TRIG_BUSY_BITS) != 0;}
#endif
