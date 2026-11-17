#ifndef S3_MOCK_PIO_H
#define S3_MOCK_PIO_H
#include <stdbool.h>
#include <stdint.h>
typedef unsigned int uint;
typedef struct { uint32_t rxf[4]; } *PIO;
typedef struct { int unused; } pio_sm_config;
struct pio_program { const uint16_t *instructions; uint length; int origin; };
extern unsigned mock_fifo_clears, mock_pio_disables, mock_releases;
static inline pio_sm_config pio_get_default_sm_config(void) { return (pio_sm_config){0}; }
static inline void sm_config_set_wrap(pio_sm_config *c,uint a,uint b) {(void)c;(void)a;(void)b;}
static inline void sm_config_set_in_pins(pio_sm_config *c,uint p) {(void)c;(void)p;}
static inline void sm_config_set_jmp_pin(pio_sm_config *c,uint p) {(void)c;(void)p;}
static inline void sm_config_set_set_pins(pio_sm_config *c,uint p,uint n) {(void)c;(void)p;(void)n;}
#define PIO_FIFO_JOIN_RX 1
static inline void sm_config_set_fifo_join(pio_sm_config *c,int f) {(void)c;(void)f;}
static inline void sm_config_set_clkdiv_int_frac(pio_sm_config *c,uint16_t i,uint8_t f) {(void)c;(void)i;(void)f;}
static inline bool pio_claim_free_sm_and_add_program(const struct pio_program *p,PIO *io,uint *sm,uint *offset) {(void)p;(void)io;(void)sm;(void)offset;return false;}
static inline void pio_remove_program_and_unclaim_sm(const struct pio_program *p,PIO io,uint sm,uint off) {(void)p;(void)io;(void)sm;(void)off;}
static inline int pio_sm_init(PIO p,uint s,uint off,const pio_sm_config *c) {(void)p;(void)s;(void)off;(void)c;return 0;}
static inline void pio_sm_set_consecutive_pindirs(PIO p,uint s,uint pin,uint count,bool out) {(void)p;(void)s;(void)pin;(void)count;if(!out) ++mock_releases;}
static inline void pio_sm_set_enabled(PIO p,uint s,bool enabled) {(void)p;(void)s;if(!enabled) ++mock_pio_disables;}
static inline void pio_sm_restart(PIO p,uint s) {(void)p;(void)s;}
static inline void pio_sm_clear_fifos(PIO p,uint s) {(void)p;(void)s;++mock_fifo_clears;}
static inline void pio_sm_clkdiv_restart(PIO p,uint s) {(void)p;(void)s;}
static inline void pio_sm_exec(PIO p,uint s,uint instr) {(void)p;(void)s;(void)instr;}
static inline uint pio_encode_jmp(uint offset) {return offset;}
static inline uint pio_get_dreq(PIO p,uint s,bool tx) {(void)p;(void)s;(void)tx;return 0;}
static inline void gpio_init(uint p) {(void)p;}
static inline void gpio_pull_up(uint p) {(void)p;}
static inline void pio_gpio_init(PIO io,uint p) {(void)io;(void)p;}
#endif
